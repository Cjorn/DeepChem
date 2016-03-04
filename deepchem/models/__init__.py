"""
Contains an abstract base class that supports different ML models.
"""
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals
import sys
import numpy as np
import pandas as pd
import joblib
import os
from deepchem.utils.dataset import Dataset
from deepchem.utils.dataset import load_from_disk
from deepchem.utils.dataset import save_to_disk
from deepchem.utils.save import log

def undo_transforms(y, transformers):
  """Undoes all transformations applied."""
  # Note that transformers have to be undone in reversed order
  for transformer in reversed(transformers):
    y = transformer.untransform(y)
  return y

class Model(object):
  """
  Abstract base class for different ML models.
  """
  non_sklearn_models = ["SingleTaskDNN", "MultiTaskDNN", "DockingDNN"]
  def __init__(self, task_types, model_params, model_instance=None,
               initialize_raw_model=True, verbosity="low", **kwargs):
    self.model_class = model_instance.__class__
    self.task_types = task_types
    self.model_params = model_params
    self.raw_model = None
    assert verbosity in [None, "low", "high"]
    self.low_verbosity = (verbosity == "low")
    self.high_verbosity = (verbosity == "high")

  def fit_on_batch(self, X, y, w):
    """
    Updates existing model with new information.
    """
    raise NotImplementedError(
        "Each model is responsible for its own fit_on_batch method.")

  def predict_on_batch(self, X):
    """
    Makes predictions on given batch of new data.
    """
    raise NotImplementedError(
        "Each model is responsible for its own predict_on_batch method.")

  def set_raw_model(self, raw_model):
    """
    Set underlying raw model. Useful when loading from disk.
    """
    self.raw_model = raw_model

  def get_raw_model(self):
    """
    Return raw model.
    """
    return self.raw_model

  @staticmethod
  def get_model_filename(out_dir):
    """
    Given model directory, obtain filename for the model itself.
    """
    return os.path.join(out_dir, "model.joblib")

  @staticmethod
  def get_params_filename(out_dir):
    """
    Given model directory, obtain filename for the model itself.
    """
    return os.path.join(out_dir, "model_params.joblib")

  @staticmethod
  def get_task_type(model_name):
    """
    Given model type, determine if classifier or regressor.
    """
    if model_name in ["logistic", "rf_classifier", "singletask_deep_classifier",
                      "multitask_deep_classifier"]:
      return "classification"
    else:
      return "regression"

  def save(self, out_dir):
    """Dispatcher function for saving."""
    params = {"model_params" : self.model_params,
              "task_types" : self.task_types,
              "model_class": self.__class__}
    save_to_disk(params, Model.get_params_filename(out_dir))

  def fit(self, dataset):
    """
    Fits a model on data in a Dataset object.
    """
    # TODO(rbharath/enf): We need a structured way to deal with potential GPU
    #                     memory overflows.
    batch_size = self.model_params["batch_size"]
    for epoch in range(self.model_params["nb_epoch"]):
      log("Starting epoch %s" % str(epoch+1), self.low_verbosity)
      for i, (X, y, w, _) in enumerate(dataset.itershards()):
        log("Training on shard-%s/epoch-%s" % (str(i+1), str(epoch+1)),
        self.high_verbosity)
        nb_sample = np.shape(X)[0]
        interval_points = np.linspace(
            0, nb_sample, np.ceil(float(nb_sample)/batch_size)+1, dtype=int)
        for j in range(len(interval_points)-1):
          log("Training on batch-%s/shard-%s/epoch-%s" %
              (str(j+1), str(i+1), str(epoch+1)), self.high_verbosity)
          indices = range(interval_points[j], interval_points[j+1])
          X_batch = X[indices, :]
          y_batch = y[indices]
          w_batch = w[indices]
          self.fit_on_batch(X_batch, y_batch, w_batch)

  # TODO(rbharath): The structure of the produced df might be
  # complicated. Better way to model?
  def predict(self, dataset, transformers):
    """
    Uses self to make predictions on provided Dataset object.
    """
    task_names = dataset.get_task_names()
    pred_task_names = ["%s_pred" % task_name for task_name in task_names]
    w_task_names = ["%s_weight" % task_name for task_name in task_names]
    raw_task_names = [task_name+"_raw" for task_name in task_names]
    raw_pred_task_names = [pred_task_name+"_raw" for pred_task_name in pred_task_names]
    column_names = (['ids'] + raw_task_names + task_names
                    + raw_pred_task_names + pred_task_names + w_task_names
                    + ["y_means", "y_stds"])
    pred_y_df = pd.DataFrame(columns=column_names)

    batch_size = self.model_params["batch_size"]
    for (X, y, w, ids) in dataset.itershards():
      nb_sample = np.shape(X)[0]
      interval_points = np.linspace(
          0, nb_sample, np.ceil(float(nb_sample)/batch_size)+1, dtype=int)
      y_preds = []
      for j in range(len(interval_points)-1):
        indices = range(interval_points[j], interval_points[j+1])
        y_pred_on_batch = self.predict_on_batch(X[indices, :]).reshape(
            (len(indices),len(task_names)))
        y_preds.append(y_pred_on_batch)

      y_pred = np.concatenate(y_preds)
      y_pred = np.reshape(y_pred, np.shape(y))

      # Now undo transformations on y, y_pred
      y_raw, y_pred_raw = y, y_pred
      y = undo_transforms(y, transformers)
      y_pred = undo_transforms(y_pred, transformers)

      shard_df = pd.DataFrame(columns=column_names)
      shard_df['ids'] = ids
      shard_df[raw_task_names] = y_raw
      shard_df[task_names] = y
      shard_df[raw_pred_task_names] = y_pred_raw
      shard_df[pred_task_names] = y_pred
      shard_df[w_task_names] = w
      pred_y_df = pd.concat([pred_y_df, shard_df])

    return pred_y_df
