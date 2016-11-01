"""
Contains an abstract base class that supports chemically aware data splits.
"""
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

__author__ = "Bharath Ramsundar"
__copyright__ = "Copyright 2016, Stanford University"
__license__ = "GPL"

import tempfile
import numpy as np
from rdkit import Chem
from deepchem.utils import ScaffoldGenerator
from deepchem.utils.save import log
from deepchem.datasets import NumpyDataset
from deepchem.featurizers.featurize import load_data
from deepchem.splits import Splitter

def merge_fold_datasets(fold_datasets):
  """Merges fold datasets together.

  Assumes that fold_datasets were outputted from k_fold_split. Specifically,
  assumes that each dataset contains the same datapoints, listed in the same
  ordering.
  """
  if not len(fold_datasets):
    return None

  # All datasets share features and identifiers by assumption.
  X = fold_datasets[0].X
  ids = fold_datasets[0].ids

  ys, ws = [], []
  for fold_dataset in fold_datasets:
    ys.append(fold_dataset.y)
    ws.append(fold_dataset.w)
  y = np.concatenate(ys, axis=1)
  w = np.concatenate(ws, axis=1)
  return NumpyDataset(X, y, w, ids)

class TaskSplitter(Splitter):
  """
  Provides a simple interface for splitting datasets task-wise.

  For some learning problems, the training and test datasets should
  have different tasks entirely. This is a different paradigm from the
  usual Splitter, which ensures that split datasets have different
  datapoints, not different tasks.
  """

  def __init__(self):
    "Creates Task Splitter object."
    pass

  def train_valid_test_split(self, dataset, frac_train=.8, frac_valid=.1,
                             frac_test=.1):
    """Performs a train/valid/test split of the tasks for dataset.

    Parameters
    ----------
    dataset: deepchem.datasets.Dataset
      Dataset to be split
    frac_train: float, optional
      Proportion of tasks to be put into train. Rounded to nearest int.
    frac_valid: float, optional
      Proportion of tasks to be put into valid. Rounded to nearest int.
    frac_test: float, optional
      Proportion of tasks to be put into test. Rounded to nearest int.
    """
    n_tasks = len(dataset.get_task_names())
    n_train = int(np.round(frac_train * n_tasks))
    n_valid = int(np.round(frac_valid * n_tasks))
    n_test = int(np.round(frac_test * n_tasks))
    if n_train + n_valid + n_test != n_tasks:
      raise ValueError("Train/Valid/Test fractions don't split tasks evenly.")

    X, y, w, ids = dataset.X, dataset.y, dataset.w, dataset.ids
    
    train_dataset = NumpyDataset(X, y[:,:n_train], w[:,:n_train], ids)
    valid_dataset = NumpyDataset(
        X, y[:,n_train:n_train+n_valid], w[:,n_train:n_train+n_valid], ids)
    test_dataset = NumpyDataset(
        X, y[:,n_train+n_valid:], w[:,n_train+n_valid:], ids)
    return train_dataset, valid_dataset, test_dataset

  def k_fold_split(self, dataset, K):
    """Performs a K-fold split of the tasks for dataset.

    Parameters
    ----------
    dataset: deepchem.datasets.Dataset
      Dataset to be split
    K: int
      Number of splits to be made
    """
    n_tasks = len(dataset.get_task_names())
    n_per_fold = int(np.round(n_tasks/float(K)))
    if K * n_per_fold != n_tasks:
      raise ValueError("Cannot perform a valid %d-way split" % K)
    
    X, y, w, ids = dataset.X, dataset.y, dataset.w, dataset.ids

    fold_datasets = []
    for fold in range(K):
      fold_tasks = range(fold*n_per_fold, (fold+1)*n_per_fold)
      fold_datasets.append(
          NumpyDataset(X, y[:, fold_tasks], w[:, fold_tasks], ids))
    return fold_datasets
