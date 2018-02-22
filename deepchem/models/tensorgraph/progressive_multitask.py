from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import time
import numpy as np
import tensorflow as tf
import collections

from deepchem.utils.save import log
from deepchem.metrics import to_one_hot
from deepchem.metrics import from_one_hot
from deepchem.models.tensorgraph.tensor_graph import TensorGraph, TFWrapper
from deepchem.models.tensorgraph.layers import Layer, Feature, Label, Weights, \
    WeightedError, Dense, Dropout, WeightDecay, Reshape, SoftMaxCrossEntropy, \
    L2Loss, ReduceSum, Concat, Stack, TensorWrapper, ReLU


class ProgressiveMultitaskRegressor(TensorGraph):
  """Implements a progressive multitask neural network.
  
  Progressive Networks: https://arxiv.org/pdf/1606.04671v3.pdf

  Progressive networks allow for multitask learning where each task
  gets a new column of weights. As a result, there is no exponential
  forgetting where previous tasks are ignored.

  """

  def __init__(self,
               n_tasks,
               n_features,
               alpha_init_stddevs=0.02,
               layer_sizes=[1000],
               weight_init_stddevs=0.02,
               bias_init_consts=1.0,
               weight_decay_penalty=0.0,
               weight_decay_penalty_type="l2",
               dropouts=0.5,
               activation_fns=tf.nn.relu,
               **kwargs):
    """Creates a progressive network.
  
    Only listing parameters specific to progressive networks here.

    Parameters
    ----------
    n_tasks: int
      Number of tasks
    n_features: int
      Number of input features
    alpha_init_stddevs: list
      List of standard-deviations for alpha in adapter layers.
    layer_sizes: list
      the size of each dense layer in the network.  The length of this list determines the number of layers.
    weight_init_stddevs: list or float
      the standard deviation of the distribution to use for weight initialization of each layer.  The length
      of this list should equal len(layer_sizes)+1.  The final element corresponds to the output layer.
      Alternatively this may be a single value instead of a list, in which case the same value is used for every layer.
    bias_init_consts: list or float
      the value to initialize the biases in each layer to.  The length of this list should equal len(layer_sizes)+1.
      The final element corresponds to the output layer.  Alternatively this may be a single value instead of a list,
      in which case the same value is used for every layer.
    weight_decay_penalty: float
      the magnitude of the weight decay penalty to use
    weight_decay_penalty_type: str
      the type of penalty to use for weight decay, either 'l1' or 'l2'
    dropouts: list or float
      the dropout probablity to use for each layer.  The length of this list should equal len(layer_sizes).
      Alternatively this may be a single value instead of a list, in which case the same value is used for every layer.
    activation_fns: list or object
      the Tensorflow activation function to apply to each layer.  The length of this list should equal
      len(layer_sizes).  Alternatively this may be a single value instead of a list, in which case the
      same value is used for every layer.
    """

    super(ProgressiveMultitaskRegressor, self).__init__(**kwargs)
    self.n_tasks = n_tasks
    self.n_features = n_features
    self.layer_sizes = layer_sizes
    self.alpha_init_stddevs = alpha_init_stddevs
    self.weight_init_stddevs = weight_init_stddevs
    self.bias_init_consts = bias_init_consts
    self.dropouts = dropouts
    self.activation_fns = activation_fns

    n_layers = len(layer_sizes)
    if not isinstance(weight_init_stddevs, collections.Sequence):
      self.weight_init_stddevs = [weight_init_stddevs] * n_layers
    if not isinstance(alpha_init_stddevs, collections.Sequence):
      self.alpha_init_stddevs = [alpha_init_stddevs] * n_layers
    if not isinstance(bias_init_consts, collections.Sequence):
      self.bias_init_consts = [bias_init_consts] * n_layers
    if not isinstance(dropouts, collections.Sequence):
      self.dropouts = [dropouts] * n_layers
    if not isinstance(activation_fns, collections.Sequence):
      self.activation_fns = [activation_fns] * n_layers

    # Add the input features.
    self.mol_features = Feature(shape=(None, n_features))

    all_layers = {}
    outputs = []
    for task in range(self.n_tasks):
      task_layers = []
      for i in range(n_layers):
        if i == 0:
          prev_layer = self.mol_features
        else:
          prev_layer = all_layers[(i - 1, task)]
          if task > 0:
            lateral_contrib, trainables = self.add_adapter(all_layers, task, i)
            task_layers.extend(trainables)

        layer = Dense(
            in_layers=[prev_layer],
            out_channels=layer_sizes[i],
            activation_fn=None,
            weights_initializer=TFWrapper(
                tf.truncated_normal_initializer,
                stddev=self.weight_init_stddevs[i]),
            biases_initializer=TFWrapper(
                tf.constant_initializer, value=self.bias_init_consts[i]))
        task_layers.append(layer)

        if i > 0 and task > 0:
          layer = layer + lateral_contrib
        assert self.activation_fns[i] is tf.nn.relu, "Only ReLU is supported"
        layer = ReLU(in_layers=[layer])
        if self.dropouts[i] > 0.0:
          layer = Dropout(self.dropouts[i], in_layers=[layer])
        all_layers[(i, task)] = layer

      prev_layer = all_layers[(n_layers - 1, task)]
      layer = Dense(
          in_layers=[prev_layer],
          out_channels=1,
          weights_initializer=TFWrapper(
              tf.truncated_normal_initializer,
              stddev=self.weight_init_stddevs[-1]),
          biases_initializer=TFWrapper(
              tf.constant_initializer, value=self.bias_init_consts[-1]))
      task_layers.append(layer)

      if task > 0:
        lateral_contrib, trainables = self.add_adapter(all_layers, task,
                                                       n_layers)
        task_layers.extend(trainables)
        layer = layer + lateral_contrib
      outputs.append(layer)
      self.add_output(layer)
      task_label = Label(shape=(None, 1))
      task_weight = Weights(shape=(None, 1))
      weighted_loss = ReduceSum(
          L2Loss(in_layers=[task_label, layer, task_weight]))
      self.create_submodel(
          layers=task_layers, loss=weighted_loss, optimizer=None)
    # Weight decay not activated
    """
    if weight_decay_penalty != 0.0:
      weighted_loss = WeightDecay(
          weight_decay_penalty,
          weight_decay_penalty_type,
          in_layers=[weighted_loss])
    """

  def add_adapter(self, all_layers, task, layer_num):
    """Add an adapter connection for given task/layer combo"""
    i = layer_num
    prev_layers = []
    trainable_layers = []
    # Handle output layer
    if i < len(self.layer_sizes):
      layer_sizes = self.layer_sizes
      alpha_init_stddev = self.alpha_init_stddevs[i]
      weight_init_stddev = self.weight_init_stddevs[i]
      bias_init_const = self.bias_init_consts[i]
    elif i == len(self.layer_sizes):
      layer_sizes = self.layer_sizes + [1]
      alpha_init_stddev = self.alpha_init_stddevs[-1]
      weight_init_stddev = self.weight_init_stddevs[-1]
      bias_init_const = self.bias_init_consts[-1]
    else:
      raise ValueError("layer_num too large for add_adapter.")
    # Iterate over all previous tasks.
    for prev_task in range(task):
      prev_layers.append(all_layers[(i - 1, prev_task)])
    # prev_layers is a list with elements of size
    # (batch_size, layer_sizes[i-1])
    prev_layer = Concat(axis=1, in_layers=prev_layers)
    with self._get_tf("Graph").as_default():
      alpha = TensorWrapper(
          tf.Variable(
              tf.truncated_normal((1,), stddev=alpha_init_stddev),
              name="alpha_layer_%d_task%d" % (i, task)))
      trainable_layers.append(alpha)

    prev_layer = prev_layer * alpha
    dense1 = Dense(
        in_layers=[prev_layer],
        out_channels=layer_sizes[i - 1],
        activation_fn=None,
        weights_initializer=TFWrapper(
            tf.truncated_normal_initializer, stddev=weight_init_stddev),
        biases_initializer=TFWrapper(
            tf.constant_initializer, value=bias_init_const))
    trainable_layers.append(dense1)

    dense2 = Dense(
        in_layers=[dense1],
        out_channels=layer_sizes[i],
        activation_fn=None,
        weights_initializer=TFWrapper(
            tf.truncated_normal_initializer, stddev=weight_init_stddev),
        biases_initializer=None)
    trainable_layers.append(dense2)

    return dense2, trainable_layers

  def default_generator(self,
                        dataset,
                        epochs=1,
                        predict=False,
                        deterministic=True,
                        pad_batches=True):
    for epoch in range(epochs):
      for (X_b, y_b, w_b, ids_b) in dataset.iterbatches(
          batch_size=self.batch_size,
          deterministic=deterministic,
          pad_batches=pad_batches):
        feed_dict = dict()
        if X_b is not None:
          feed_dict[self.features[0]] = X_b
        if y_b is not None and not predict:
          for task in range(self.n_tasks):
            feed_dict[self.labels[task]] = y_b[:, task:task + 1]
        if w_b is not None and not predict:
          for task in range(self.n_tasks):
            feed_dict[self.task_weights[task]] = w_b[:, task:task + 1]
        yield feed_dict

  def fit(self,
          dataset,
          nb_epoch=10,
          max_checkpoints_to_keep=5,
          checkpoint_interval=1000,
          deterministic=False,
          restore=False,
          **kwargs):
    for task in range(self.n_tasks):
      self.fit_task(
          dataset,
          nb_epoch=nb_epoch,
          max_checkpoints_to_keep=max_checkpoints_to_keep,
          checkpoint_interval=checkpoint_interval,
          deterministic=deterministic,
          restore=restore,
          submodel=task,
          **kwargs)

  def fit_task(self,
               dataset,
               nb_epoch=10,
               max_checkpoints_to_keep=5,
               checkpoint_interval=1000,
               deterministic=False,
               restore=False,
               submodel=None,
               **kwargs):
    """Fit one task."""
    generator = self.default_generator(
        dataset, epochs=nb_epoch, deterministic=deterministic)
    self.fit_generator(generator, max_checkpoints_to_keep, checkpoint_interval,
                       restore, self.submodels[submodel])

  def predict_proba(self, dataset, transformers=[], outputs=None):
    return self.predict(dataset, transformers=transformers, outputs=outputs)

  def predict(self, dataset, transformers=[], outputs=None):
    retval = super(ProgressiveMultitaskRegressor, self).predict(
        dataset, transformers, outputs)
    # Results is of shape (n_samples, n_tasks, 1)
    out = np.stack(retval, axis=1)
    return out
