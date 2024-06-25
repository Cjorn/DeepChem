import torch.nn as nn
from torch.nn import GRU, LSTM
import math
from typing import List

RNN_DICT = {"GRU": GRU, "LSTM": LSTM}


class Smiles2Vec(nn.Module):
    """
    Implements the Smiles2Vec model, that learns neural representations of SMILES
    strings which can be used for downstream tasks.

    The model is based on the description in Goh et al., "SMILES2vec: An
    Interpretable General-Purpose Deep Neural Network for Predicting Chemical
    Properties" (https://arxiv.org/pdf/1712.02034.pdf). The goal here is to take
    SMILES strings as inputs, turn them into vector representations which can then
    be used in predicting molecular properties.

    The model consists of an Embedding layer that retrieves embeddings for each
    character in the SMILES string. These embeddings are learnt jointly with the
    rest of the model. The output from the embedding layer is a tensor of shape
    (batch_size, seq_len, embedding_dim). This tensor can optionally be fed
    through a 1D convolutional layer, before being passed to a series of RNN cells
    (optionally bidirectional). The final output from the RNN cells aims
    to have learnt the temporal dependencies in the SMILES string, and in turn
    information about the structure of the molecule, which is then used for
    molecular property prediction.

    In the paper, the authors also train an explanation mask to endow the model
    with interpretability and gain insights into its decision making. This segment
    is currently not a part of this implementation as this was
    developed for the purpose of investigating a transfer learning protocol,
    ChemNet (which can be found at https://arxiv.org/abs/1712.02734).
    """
    def __init__(
        self,
        char_to_idx: int,
        n_tasks: int = 10,
        max_seq_len: int = 270,
        embedding_dim: int = 50,
        n_classes: int = 2,
        use_bidir: bool = True,
        use_conv: bool = True,
        filters: int = 192,
        kernel_size: int = 3,
        strides: int = 1,
        rnn_sizes: List[int] = [224, 384],
        rnn_types: List[str] = ["GRU", "GRU"],
        mode: str = "regression",
    ):
        """
        Parameters
        ----------
        char_to_idx: dict,
            char_to_idx contains character to index mapping for SMILES characters
        embedding_dim: int, default 50
            Size of character embeddings used.
        use_bidir: bool, default True
            Whether to use BiDirectional RNN Cells
        use_conv: bool, default True
            Whether to use a conv-layer
        kernel_size: int, default 3
            Kernel size for convolutions
        filters: int, default 192
            Number of filters
        strides: int, default 1
            Strides used in convolution
        rnn_sizes: list[int], default [224, 384]
            Number of hidden units in the RNN cells
        mode: str, default regression
            Whether to use model for regression or classification
        """

        super(Smiles2Vec, self).__init__()

        self.char_to_idx = char_to_idx
        self.n_classes = n_classes
        self.max_seq_len = max_seq_len
        self.embedding_dim = embedding_dim
        self.use_bidir = use_bidir
        self.use_conv = use_conv
        if use_conv:
            self.kernel_size = kernel_size
            self.filters = filters
            self.strides = strides
        self.rnn_types = rnn_types
        self.rnn_sizes = rnn_sizes
        assert len(rnn_sizes) == len(
            rnn_types), "Should have same number of hidden units as RNNs"
        self.n_tasks = n_tasks
        self.mode = mode
        self.embedding = nn.Embedding(num_embeddings=len(self.char_to_idx),
                                      embedding_dim=self.embedding_dim)

        if use_conv:
            self.conv1d = nn.Conv1d(embedding_dim,
                                    filters,
                                    kernel_size,
                                    stride=strides)
            self.conv_output = math.floor(
                (max_seq_len - kernel_size + 1) / strides)

        self.RNN_DICT = {'RNN': nn.RNN, 'LSTM': nn.LSTM, 'GRU': nn.GRU}
        self.filters = filters
        self.rnn_sizes = rnn_sizes
        self.use_bidir = use_bidir
        self.rnn_layers = []

        # Define RNN layers
        self.rnn_layers = nn.ModuleList()
        for idx, rnn_type in enumerate(self.rnn_types):
            rnn_layer = self.RNN_DICT[rnn_type](
                input_size=self.filters if idx == 0 else self.rnn_sizes[idx -
                                                                        1],
                hidden_size=self.rnn_sizes[idx],
                batch_first=True,
                bidirectional=self.use_bidir)
            self.rnn_layers.append(rnn_layer)

        # Create the last RNN layer separately
        last_layer_input_size = self.rnn_sizes[-2] * (2
                                                      if self.use_bidir else 1)
        last_rnn_layer = RNN_DICT[self.rnn_types[-1]]
        self.last_rnn_layer = last_rnn_layer(last_layer_input_size,
                                             self.rnn_sizes[-1],
                                             batch_first=True,
                                             bidirectional=self.use_bidir)

        input_size = self.rnn_sizes[-1] * (2 if self.use_bidir else 1)

        # Define the fully connected layer for final output
        if self.mode == "classification":
            self.fc = nn.Linear(input_size, self.n_tasks * self.n_classes)
        else:
            self.fc = nn.Linear(input_size, self.n_tasks)

        if self.mode == "classification":
            if self.n_classes == 2:
                self.output_activation = nn.Sigmoid()
            else:
                self.output_activation = nn.Softmax(dim=-1)

    def forward(self, smiles_seqs: List):
        """Build the model."""
        rnn_input = self.embedding(smiles_seqs)

        if self.use_conv:

            rnn_input = rnn_input.permute(
                0, 2, 1
            )  # Convert to (batch_size, embedding_dim, seq_len) for Conv1D
            rnn_input = self.conv1d(rnn_input)
            rnn_input = rnn_input.permute(
                0, 2, 1)  # Convert back to (batch_size, seq_len, filters)

        # RNN layers
        rnn_embeddings = rnn_input
        for layer in self.rnn_layers[:-1]:
            rnn_embeddings, _ = layer(rnn_embeddings)

        # Pass through the last RNN layer
        rnn_embeddings, _ = self.last_rnn_layer(rnn_embeddings)

        # Global Average Pooling
        x = rnn_embeddings.mean(dim=1)

        Logits = self.fc(x)

        if self.mode == "classification":
            Logits = Logits.view(-1, self.n_tasks, self.n_classes)
            print(f"Shape of after reshape: {Logits}")

            output = self.output_activation(Logits)
            print(f"output: {output}")
            return Logits, output
        else:
            Logits = Logits.view(-1, self.n_tasks, 1)
            return Logits
