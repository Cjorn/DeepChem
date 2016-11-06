"""
Script that trains Keras multitask models on TOX dataset.
"""
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import os
import numpy as np
import shutil
from tox_datasets import load_tox
from deepchem.datasets import Dataset
from deepchem import metrics
from deepchem.metrics import Metric
from deepchem.utils.evaluate import Evaluator
from deepchem.models.keras_models.fcnet import MultiTaskDNN
from deepchem.models.keras_models import KerasModel

# Set some global variables up top
np.random.seed(123)
reload = True
verbosity = "high"
model = "logistic"

base_data_dir = "/tmp/toxcast_keras"

tox_tasks, dataset, transformers = load_tox(
    base_data_dir, reload=reload)
print("len(dataset)")
print(len(dataset))

base_dir = "/tmp/toxcast_analysis"
model_dir = os.path.join(base_dir, "model")
if os.path.exists(base_dir):
  shutil.rmtree(base_dir)
os.makedirs(base_dir)

# Load tox data
tox_tasks, tox_datasets, transformers = load_tox(
    base_dir, reload=reload)
train_dataset, valid_dataset = tox_datasets
n_features = 1024 


# Build model
classification_metric = Metric(metrics.roc_auc_score, np.mean,
                               verbosity=verbosity,
                               mode="classification")

learning_rates = [0.0003, 0.001, 0.003]
hidden_units = [1000, 500]
dropouts = [.5, .25]
num_hidden_layers = [1, 2]

# hyperparameter sweep here
for learning_rate in learning_rates:
  for hidden_unit in hidden_units:
    for dropout in dropouts:
      for num_hidden_layer in num_hidden_layers:
        keras_model = MultiTaskDNN(len(tox_tasks), n_features, "classification", n_hidden=hidden_unit,
                                   n_layers=num_hidden_layer, dropout=dropout, learning_rate=learning_rate, decay=1e-4)
        model = KerasModel(keras_model, self.model_dir, verbosity=verbosity)

        # Fit trained model
        model.fit(train_dataset)
        model.save()

        train_evaluator = Evaluator(model, train_dataset, transformers, verbosity=verbosity)
        train_scores = train_evaluator.compute_model_performance([classification_metric])

        print("Train scores")
        print(train_scores)

        valid_evaluator = Evaluator(model, valid_dataset, transformers, verbosity=verbosity)
        valid_scores = valid_evaluator.compute_model_performance([classification_metric])

        print("Validation scores")
        print(valid_scores)
