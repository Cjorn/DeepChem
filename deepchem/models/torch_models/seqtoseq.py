from heapq import heappush, heappushpop
from typing import List

import numpy as np

import torch.nn as nn
import torch

from deepchem.models.torch_models.layers import EncoderRNN, DecoderRNN, VariationalRandomizer
from deepchem.models.torch_models import TorchModel

from deepchem.utils.batch_utils import batch_elements, create_input_array, create_output_array


class SeqToSeq(nn.Module):

    def __init__(self,
                 n_input_tokens: int,
                 n_output_tokens: int,
                 max_output_length: int,
                 batch_size: int = 100,
                 embedding_dimension: int = 512,
                 dropout: float = 0.0,
                 variational: bool = False,
                 annealing_start_step: int = 5000,
                 annealing_final_step: int = 10000):
        """Initialize SeqToSeq model.

        Parameters
        ----------
        n_input_tokens: int
            Number of input tokens.
        n_output_tokens: int
            Number of output tokens.
        max_output_length: int
            Maximum length of output sequence.
        embedding_dimension: int (default 512)
            Width of the embedding vector. This also is the width of all recurrent
            layers.
        dropout: float (default 0.0)
            Dropout probability to use during training.
        variational: bool (default False)
            If True, train the model as a variational autoencoder. This adds random
            noise to the encoder, and also constrains the embedding to follow a unit
            Gaussian distribution.
        annealing_start_step: int
            the step (that is, batch) at which to begin turning on the constraint
            term for KL cost annealing.
        annealing_final_step: int
            the step (that is, batch) at which to finish turning on the constraint
            term for KL cost annealing.

        """
        super(SeqToSeq, self).__init__()
        self._variational = variational
        self.encoder = EncoderRNN(n_input_tokens, embedding_dimension, dropout)
        self.decoder = DecoderRNN(embedding_dimension, n_output_tokens,
                                  max_output_length, batch_size)
        if variational:
            self.randomizer = VariationalRandomizer(embedding_dimension,
                                                    annealing_start_step,
                                                    annealing_final_step)

    def forward(self, inputs: List):
        """Generates Embeddings using Encoder then passes it to Decoder to
        predict output sequences.

        Parameters
        ----------
        inputs: List
            List of two tensors.
            First tensor is batch of input sequence.
            Second tensor is the current global_step.

        Returns
        -------
        output: torch.Tensor
            Predicted output sequence.

        """
        input, global_step = inputs
        _, embedding = self.encoder(input.to(torch.long))
        self.encoder.training = False
        _, self._embedding = self.encoder(input.to(torch.long))
        self.encoder.training = True
        if self._variational:
            embedding = self.randomizer([self._embedding, global_step])
            self._embedding = self.randomizer([self._embedding, global_step],
                                              training=False)
        output, _ = self.decoder([embedding, None])
        return output


class SeqToSeqModel(TorchModel):

    sequence_end = object()

    def __init__(self,
                 input_tokens,
                 output_tokens,
                 max_output_length,
                 batch_size=100,
                 embedding_dimension=512,
                 dropout=0.0,
                 reverse_input=True,
                 variational=False,
                 annealing_start_step=5000,
                 annealing_final_step=10000,
                 **kwargs):
        """Construct a SeqToSeq model.

        Parameters
        ----------
        input_tokens: list
            List of all tokens that may appear in input sequences.
        output_tokens: list
            List of all tokens that may appear in output sequences
        max_output_length: int
            Maximum length of output sequence that may be generated
        embedding_dimension: int (default 512)
            Width of the embedding vector. This also is the width of all recurrent
            layers.
        dropout: float (default 0.0)
            Dropout probability to use during training.
        reverse_input: bool (default True)
            If True, reverse the order of input sequences before sending them into
            the encoder. This can improve performance when working with long sequences.
        variational: bool (default False)
            If True, train the model as a variational autoencoder. This adds random
            noise to the encoder, and also constrains the embedding to follow a unit
            Gaussian distribution.
        annealing_start_step: int (default 5000)
            Step (that is, batch) at which to begin turning on the constraint term
            for KL cost annealing
        annealing_final_step: int (default 10000)
            Step (that is, batch) at which to finish turning on the constraint term
            for KL cost annealing

        """
        if SeqToSeqModel.sequence_end not in input_tokens:
            input_tokens = input_tokens + [SeqToSeqModel.sequence_end]
        if SeqToSeqModel.sequence_end not in output_tokens:
            output_tokens = output_tokens + [SeqToSeqModel.sequence_end]
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._input_dict = dict((x, i) for i, x in enumerate(input_tokens))
        self._output_dict = dict((x, i) for i, x in enumerate(output_tokens))
        self._n_input_tokens = len(input_tokens)
        self._n_output_tokens = len(output_tokens)
        self._max_output_length = max_output_length
        self.batch_size = batch_size
        self._embedding_dimension = embedding_dimension
        self._dropout = dropout
        self._reverse_input = reverse_input
        self._variational = variational
        self._annealing_start_step = annealing_start_step
        self._annealing_final_step = annealing_final_step

        self.model: nn.Module = SeqToSeq(
            n_input_tokens=self._n_input_tokens,
            n_output_tokens=self._n_output_tokens,
            max_output_length=self._max_output_length,
            batch_size=self.batch_size,
            embedding_dimension=self._embedding_dimension,
            dropout=self._dropout,
            variational=self._variational,
            annealing_start_step=self._annealing_start_step,
            annealing_final_step=self._annealing_final_step)

        super(SeqToSeqModel, self).__init__(self.model,
                                            self._create_loss(),
                                            batch_size=self.batch_size,
                                            **kwargs)

    def _create_loss(self):
        """Create loss function for model."""
        if self._variational:
            loss = sum(self.model.randomizer.loss_list)
        else:
            loss = torch.tensor(0.0)

        def loss_fn(outputs, labels, weights):
            output = outputs[0].view(-1, outputs[0].size(-1))
            target = labels[0].view(-1)
            loss_ = nn.NLLLoss()(torch.log(output.to(torch.float32)),
                                 target.to(torch.int64))
            return loss + loss_

        return loss_fn

    def fit_sequences(self,
                      sequences,
                      max_checkpoints_to_keep=5,
                      checkpoint_interval=1000,
                      restore=False):
        """Train this model on a set of sequences

        Parameters
        ----------
        sequences: iterable
            the training samples to fit to.  Each sample should be
            represented as a tuple of the form (input_sequence, output_sequence).
        max_checkpoints_to_keep: int
            the maximum number of checkpoints to keep.  Older checkpoints are discarded.
        checkpoint_interval: int
            the frequency at which to write checkpoints, measured in training steps.
        restore: bool
            if True, restore the model from the most recent checkpoint and continue training
            from there.  If False, retrain the model from scratch.
        """
        loss = self.fit_generator(
            self._generate_batches(sequences),
            max_checkpoints_to_keep=max_checkpoints_to_keep,
            checkpoint_interval=checkpoint_interval,
            restore=restore)
        return loss

    def predict_from_sequences(self, sequences, beam_width):
        """Given a set of input sequences, predict the output sequences.

        The prediction is done using a beam search with length normalization.

        Parameters
        ----------
        sequences: iterable
            the input sequences to generate a prediction for
        beam_width: int
            the beam width to use for searching.  Set to 1 to use a simple greedy search.
        """
        result = []
        for batch in batch_elements(sequences, self.batch_size):
            features = create_input_array(batch, self._max_output_length,
                                          self._reverse_input, self.batch_size,
                                          self._input_dict,
                                          SeqToSeqModel.sequence_end)
            probs = self.predict_on_generator([[
                (features, np.array(self.get_global_step())), None, None
            ]])
            for i in range(len(batch)):
                result.append(self._beam_search(probs[i], beam_width))
        return result

    def predict_from_embeddings(self, embeddings, beam_width=5):
        """Given a set of embedding vectors, predict the output sequences.

        The prediction is done using a beam search with length normalization.

        Parameters
        ----------
        embeddings: iterable
            the embedding vectors to generate predictions for
        beam_width: int
            the beam width to use for searching.  Set to 1 to use a simple greedy search.
        """
        result = []
        for batch in batch_elements(embeddings, self.batch_size):
            embedding_array = np.zeros(
                (self.batch_size, self._embedding_dimension), dtype=np.float32)
            for i, e in enumerate(batch):
                embedding_array[i] = e
            probs, _ = self.model.decoder([torch.tensor(embedding_array, device=self.device).unsqueeze(0), None])
            probs = probs.cpu().detach().numpy()
            for i in range(len(batch)):
                result.append(self._beam_search(probs[i], beam_width))
        return result

    def predict_embeddings(self, sequences):
        """Given a set of input sequences, compute the embedding vectors.

        Parameters
        ----------
        sequences: iterable
            the input sequences to generate an embedding vector for
        """
        result = []
        for batch in batch_elements(sequences, self.batch_size):
            features = create_input_array(batch, self._max_output_length,
                                          self._reverse_input, self.batch_size,
                                          self._input_dict,
                                          SeqToSeqModel.sequence_end)
            _ = self.predict_on_generator([[(features,
                                             np.array(self.get_global_step())),
                                            None, None]])
            embeddings = np.squeeze(
                self.model._embedding.cpu().detach().numpy())
            for i in range(len(batch)):
                result.append(embeddings[i])
        return np.array(result, dtype=np.float32)

    def _beam_search(self, probs, beam_width):
        """Perform a beam search for the most likely output sequence."""
        if beam_width == 1:
            # Do a simple greedy search.

            s = []
            for i in range(len(probs)):
                token = self._output_tokens[np.argmax(probs[i])]
                if token == SeqToSeqModel.sequence_end:
                    break
                s.append(token)
            return s

        # Do a beam search with length normalization.

        logprobs = np.log(probs)
        # Represent each candidate as (normalized prob, raw prob, sequence)
        candidates = [(0.0, 0.0, [])]
        for i in range(len(logprobs)):
            new_candidates = []
            for c in candidates:
                if len(c[2]) > 0 and c[2][-1] == SeqToSeqModel.sequence_end:
                    # This candidate sequence has already been terminated
                    if len(new_candidates) < beam_width:
                        heappush(new_candidates, c)
                    else:
                        heappushpop(new_candidates, c)
                else:
                    # Consider all possible tokens we could add to this candidate sequence.
                    for j, logprob in enumerate(logprobs[i]):
                        new_logprob = logprob + c[1]
                        newc = (new_logprob / (len(c[2]) + 1), new_logprob,
                                c[2] + [self._output_tokens[j]])
                        if len(new_candidates) < beam_width:
                            heappush(new_candidates, newc)
                        else:
                            heappushpop(new_candidates, newc)
            candidates = new_candidates
        return sorted(candidates)[-1][2][:-1]

    def _generate_batches(self, sequences):
        """Create feed_dicts for fitting."""
        for batch in batch_elements(sequences, self.batch_size):
            inputs = []
            outputs = []
            for input, output in batch:
                inputs.append(input)
                outputs.append(output)
            for i in range(len(inputs), self.batch_size):
                inputs.append([])
                outputs.append([])
            features = create_input_array(inputs, self._max_output_length,
                                          self._reverse_input, self.batch_size,
                                          self._input_dict,
                                          SeqToSeqModel.sequence_end)
            labels = create_output_array(outputs, self._max_output_length,
                                         self.batch_size, self._output_dict,
                                         SeqToSeqModel.sequence_end)
            yield ([features, np.array(self.get_global_step())], [labels], [])
