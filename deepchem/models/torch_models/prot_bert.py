from transformers import BertForMaskedLM, BertForSequenceClassification, BertTokenizer, BertConfig
import torch.nn as nn
from deepchem.models.torch_models.hf_models import HuggingFaceModel
from typing import Union


class ProtBERT(HuggingFaceModel):
    """
    ProtBERT model[1].

    ProtBERT model is based on BERT architecture and the current implementation
    supports only MLM pretraining and classification mode, as described by the
    authors in HuggingFace[2]. For classfication we currently only support
    Logistic regression and a simple Feed forward neural network.

    The model converts the input protein sequence into a vector through a trained BERT tokenizer, which is then
    processed by the corresponding model based on the task. `BertForMaskedLM` is used to facilitate the MLM
    pretraining task. For the sequence classification task, we follow `BertForSequenceClassification` but change
    the classifier to either a logistic regression (LogReg) or a feed-forward neural network (FFN), depending on
    the specified `cls_name`. The FFN is a simple 2-layer network with 512 as the hidden dimension.


    Examples
    --------
    >>> import os
    >>> import tempfile
    >>> tempdir = tempfile.mkdtemp()

    >>> # preparing dataset
    >>> import pandas as pd
    >>> import deepchem as dc
    >>> protein = ["MPCTTYLPLLLLLFLLPPPSVQSKV","SSGLFWMELLTQFVLTWPLVVIAFL"]
    >>> labels = [0,1]
    >>> df = pd.DataFrame(list(zip(protein, labels)), columns=["protein", "task1"])
    >>> with dc.utils.UniversalNamedTemporaryFile(mode='w') as tmpfile:
    ...     df.to_csv(tmpfile.name)
    ...     loader = dc.data.CSVLoader(["task1"], feature_field="protein", featurizer=dc.feat.DummyFeaturizer())
    ...     dataset = loader.create_dataset(tmpfile.name)

    >>> # pretraining
    >>> from deepchem.models.torch_models.prot_bert import ProtBERT
    >>> pretrain_model_dir = os.path.join(tempdir, 'pretrain-model')
    >>> model_path = 'Rostlab/prot_bert'
    >>> pretrain_model = ProtBERT(task='mlm', HG_model_path=model_path, n_tasks=1, model_dir=pretrain_model_dir)  # mlm pretraining
    >>> pretraining_loss = pretrain_model.fit(dataset, nb_epoch=1)
    >>> del pretrain_model

    >>> finetune_model_dir = os.path.join(tempdir, 'finetune-model')
    >>> finetune_model = ProtBERT(task='classification', HG_model_path=model_path, n_tasks=1, model_dir=finetune_model_dir)
    >>> finetune_model.load_from_pretrained(pretrain_model_dir)
    >>> finetuning_loss = finetune_model.fit(dataset, nb_epoch=1)

    >>> # prediction and evaluation
    >>> result = finetune_model.predict(dataset)
    >>> eval_results = finetune_model.evaluate(dataset, metrics=dc.metrics.Metric(dc.metrics.accuracy_score))

    References
    ----------
    .. [1] Elnaggar, Ahmed, et al. "Prottrans: Toward understanding the language of life through self-supervised learning." IEEE transactions on pattern analysis and machine intelligence 44.10 (2021): 7112-7127.
    .. [2] https://huggingface.co/Rostlab/prot_bert

    """

    def __init__(self,
                 task: str,
                 model_pretrain_dataset = "uniref100",
                 n_tasks: int = 1,
                 cls_name: str = "LogReg",
                 **kwargs) -> None:
        """
        Parameters
        ----------
        task: str
            The task defines the type of learning task in the model. The supported tasks are
            - `mlm` - masked language modeling commonly used in pretraining
            - `classification` - use it for classification tasks
        model_path: str
            Path to the HuggingFace model
        n_tasks: int, default 1
            Number of prediction targets for a multitask learning model
        cls_name: str
            The classifier head to use for classification mode. Currently only supports "FFN" and "LogReg"
        """

        

        self.n_tasks: int = n_tasks
        tokenizer: BertTokenizer 
        model: Union[BertForMaskedLM, BertForSequenceClassification]

        if(model_pretrain_dataset == "uniref100"):
            model_path = 'Rostlab/prot_bert'
        elif(model_pretrain_dataset == "bfd"):
            model_path = 'Rostlab/prot_bert_bfd'
        else:
            raise ValueError('Invalid pretraining data: {}.'.format(model_pretrain_dataset))

        tokenizer =  BertTokenizer.from_pretrained(
            model_path, do_lower_case=False)

        if task == "mlm":
            model = BertForMaskedLM.from_pretrained(model_path)
        elif task == "classification":
            cls_head: Union[nn.Linear, nn.Sequential]
            protbert_config: BertConfig = BertConfig.from_pretrained(
            pretrained_model_name_or_path=model_path,
            vocab_size=tokenizer.vocab_size)
            if n_tasks == 1:
                protbert_config.problem_type = 'single_label_classification'
            else:
                protbert_config.problem_type = 'multi_label_classification'

            if (cls_name == "LogReg"):
                cls_head = nn.Linear(1024, n_tasks + 1)
            elif (cls_name == "FFN"):
                cls_head = nn.Sequential(nn.Linear(1024, 512), nn.ReLU(),
                                         nn.Linear(512, n_tasks + 1))

            else:
                raise ValueError('Invalid classifier: {}.'.format(cls_name))

            model = BertForSequenceClassification.from_pretrained(
                model_path, config=protbert_config)
            model.classifier = cls_head

        else:
            raise ValueError('Invalid task specification')
        super().__init__(model=model, task=task, tokenizer=tokenizer, **kwargs)
