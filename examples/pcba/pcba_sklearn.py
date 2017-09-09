"""
Script that trains Sklearn multitask models on PCBA dataset.
"""
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import os
import numpy as np
import shutil
from pcba_datasets import load_pcba
from sklearn.ensemble import RandomForestClassifier
from deepchem.models.multitask import SingletaskToMultitask
from deepchem import metrics
from deepchem.metrics import Metric
from deepchem.models.sklearn_models import SklearnModel
from deepchem.utils.evaluate import Evaluator

np.random.seed(123)

# If you wish to save a particular featurization to reduce future computation time, set save_featurized_to_disk to True; set load_featurized_from_disk to True to load a previously-featurized dataset
save_featurized_to_disk = False
load_featurized_from_disk = True
is_verbose = False

base_dir = "/tmp/pcba_sklearn"
model_dir = os.path.join(base_dir, "model")
if os.path.exists(base_dir):
  shutil.rmtree(base_dir)
os.makedirs(base_dir)

pcba_tasks, pcba_datasets, transformers = load_pcba(
    save_to_disk=save_featurized_to_disk,
    load_from_disk=load_featurized_from_disk)
(train_dataset, valid_dataset, test_dataset) = pcba_datasets

classification_metric = Metric(
    metrics.roc_auc_score, np.mean, verbose=is_verbose, mode="classification")


def model_builder(model_dir):
  sklearn_model = RandomForestClassifier(
      class_weight="balanced", n_estimators=500, n_jobs=-1)
  return SklearnModel(sklearn_model, model_dir)


model = SingletaskToMultitask(pcba_tasks, model_builder, model_dir)

# Fit trained model
model.fit(train_dataset)
model.save()

train_evaluator = Evaluator(
    model, train_dataset, transformers, verbose=is_verbose)
train_scores = train_evaluator.compute_model_performance(
    [classification_metric])

print("Train scores")
print(train_scores)

valid_evaluator = Evaluator(
    model, valid_dataset, transformers, verbose=is_verbose)
valid_scores = valid_evaluator.compute_model_performance(
    [classification_metric])

print("Validation scores")
print(valid_scores)
