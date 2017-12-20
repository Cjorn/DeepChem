"""Custom Keras Layers.
"""
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

__author__ = "Han Altae-Tran and Bharath Ramsundar"
__copyright__ = "Copyright 2016, Stanford University"
__license__ = "MIT"

import warnings
import numpy as np
import tensorflow as tf
from deepchem.nn import activations
from deepchem.nn import initializations
from deepchem.nn import model_ops
from deepchem.nn.copy import Layer
from deepchem.nn.copy import Input
from deepchem.nn.copy import Dense
from deepchem.nn.copy import Dropout


def affine(x, W, b):
  return tf.matmul(x, W) + b


def tf_affine(x, vm, scope):
  W = vm.var(scope, 'W')
  b = vm.var(scope, 'b')

  return tf.matmul(x, W) + b


def sum_neigh(atoms, deg_adj_lists, max_deg):
  """Store the summed atoms by degree"""
  deg_summed = max_deg * [None]

  # Tensorflow correctly processes empty lists when using concat
  for deg in range(1, max_deg + 1):
    gathered_atoms = tf.gather(atoms, deg_adj_lists[deg - 1])
    # Sum along neighbors as well as self, and store
    summed_atoms = tf.reduce_sum(gathered_atoms, 1)
    deg_summed[deg - 1] = summed_atoms

  return deg_summed


def graph_conv(atoms, deg_adj_lists, deg_slice, max_deg, min_deg, W_list,
               b_list):
  """Core tensorflow function implementing graph convolution

  Parameters
  ----------
  atoms: tf.Tensor
    Should be of shape (n_atoms, n_feat)
  deg_adj_lists: list
    Of length (max_deg+1-min_deg). The deg-th element is a list of
    adjacency lists for atoms of degree deg.
  deg_slice: tf.Tensor
    Of shape (max_deg+1-min_deg,2). Explained in GraphTopology.
  max_deg: int
    Maximum degree of atoms in molecules.
  min_deg: int
    Minimum degree of atoms in molecules
  W_list: list
    List of learnable weights for convolution.
  b_list: list
    List of learnable biases for convolution.

  Returns
  -------
  tf.Tensor
    Of shape (n_atoms, n_feat)
  """
  W = iter(W_list)
  b = iter(b_list)

  #Sum all neighbors using adjacency matrix
  deg_summed = sum_neigh(atoms, deg_adj_lists, max_deg)

  # Get collection of modified atom features
  new_rel_atoms_collection = (max_deg + 1 - min_deg) * [None]

  for deg in range(1, max_deg + 1):
    # Obtain relevant atoms for this degree
    rel_atoms = deg_summed[deg - 1]

    # Get self atoms
    begin = tf.stack([deg_slice[deg - min_deg, 0], 0])
    size = tf.stack([deg_slice[deg - min_deg, 1], -1])
    self_atoms = tf.slice(atoms, begin, size)

    # Apply hidden affine to relevant atoms and append
    rel_out = affine(rel_atoms, next(W), next(b))
    self_out = affine(self_atoms, next(W), next(b))
    out = rel_out + self_out

    new_rel_atoms_collection[deg - min_deg] = out

  # Determine the min_deg=0 case
  if min_deg == 0:
    deg = 0

    begin = tf.stack([deg_slice[deg - min_deg, 0], 0])
    size = tf.stack([deg_slice[deg - min_deg, 1], -1])
    self_atoms = tf.slice(atoms, begin, size)

    # Only use the self layer
    out = affine(self_atoms, next(W), next(b))

    new_rel_atoms_collection[deg - min_deg] = out

  # Combine all atoms back into the list
  activated_atoms = tf.concat(axis=0, values=new_rel_atoms_collection)

  return activated_atoms


def graph_gather(atoms, membership_placeholder, batch_size):
  """
  Parameters
  ----------
  atoms: tf.Tensor
    Of shape (n_atoms, n_feat)
  membership_placeholder: tf.Placeholder
    Of shape (n_atoms,). Molecule each atom belongs to.
  batch_size: int
    Batch size for deep model.

  Returns
  -------
  tf.Tensor
    Of shape (batch_size, n_feat)
  """

  # WARNING: Does not work for Batch Size 1! If batch_size = 1, then use reduce_sum!
  assert batch_size > 1, "graph_gather requires batches larger than 1"

  # Obtain the partitions for each of the molecules
  activated_par = tf.dynamic_partition(atoms, membership_placeholder,
                                       batch_size)

  # Sum over atoms for each molecule
  sparse_reps = [
      tf.reduce_sum(activated, 0, keep_dims=True) for activated in activated_par
  ]

  # Get the final sparse representations
  sparse_reps = tf.concat(axis=0, values=sparse_reps)

  return sparse_reps


def graph_pool(atoms, deg_adj_lists, deg_slice, max_deg, min_deg):
  """
  Parameters
  ----------
  atoms: tf.Tensor
    Of shape (n_atoms, n_feat)
  deg_adj_lists: list
    Of length (max_deg+1-min_deg). The deg-th element is a list of
    adjacency lists for atoms of degree deg.
  deg_slice: tf.Tensor
    Of shape (max_deg+1-min_deg,2). Explained in GraphTopology.
  max_deg: int
    Maximum degree of atoms in molecules.
  min_deg: int
    Minimum degree of atoms in molecules

  Returns
  -------
  tf.Tensor
    Of shape (batch_size, n_feat)
  """
  # Store the summed atoms by degree
  deg_maxed = (max_deg + 1 - min_deg) * [None]

  # Tensorflow correctly processes empty lists when using concat

  for deg in range(1, max_deg + 1):
    # Get self atoms
    begin = tf.stack([deg_slice[deg - min_deg, 0], 0])
    size = tf.stack([deg_slice[deg - min_deg, 1], -1])
    self_atoms = tf.slice(atoms, begin, size)

    # Expand dims
    self_atoms = tf.expand_dims(self_atoms, 1)

    # always deg-1 for deg_adj_lists
    gathered_atoms = tf.gather(atoms, deg_adj_lists[deg - 1])
    gathered_atoms = tf.concat(axis=1, values=[self_atoms, gathered_atoms])

    maxed_atoms = tf.reduce_max(gathered_atoms, 1)
    deg_maxed[deg - min_deg] = maxed_atoms

  if min_deg == 0:
    begin = tf.stack([deg_slice[0, 0], 0])
    size = tf.stack([deg_slice[0, 1], -1])
    self_atoms = tf.slice(atoms, begin, size)
    deg_maxed[0] = self_atoms

  return tf.concat(axis=0, values=deg_maxed)


class AttnLSTMEmbedding(Layer):
  """Implements AttnLSTM as in matching networks paper.

  References:
  Matching Networks for One Shot Learning
  https://arxiv.org/pdf/1606.04080v1.pdf

  Order Matters: Sequence to sequence for sets
  https://arxiv.org/abs/1511.06391
  """

  def __init__(self,
               n_test,
               n_support,
               n_feat,
               max_depth,
               init='glorot_uniform',
               activation='linear',
               dropout=None,
               **kwargs):
    """
    Parameters
    ----------
    n_support: int
      Size of support set.
    n_test: int
      Size of test set.
    n_feat: int
      Number of features per atom
    max_depth: int
      Number of "processing steps" used by sequence-to-sequence for sets model.
    init: str, optional
      Type of initialization of weights
    activation: str, optional
      Activation for layers.
    dropout: float, optional
      Dropout probability
    """
    super(AttnLSTMEmbedding, self).__init__(**kwargs)

    self.init = initializations.get(init)  # Set weight initialization
    self.activation = activations.get(activation)  # Get activations
    self.max_depth = max_depth
    self.n_test = n_test
    self.n_support = n_support
    self.n_feat = n_feat

  def get_output_shape_for(self, input_shape):
    """Returns the output shape. Same as input_shape.

    Parameters
    ----------
    input_shape: list
      Will be of form [(n_test, n_feat), (n_support, n_feat)]

    Returns
    -------
    list
      Of same shape as input [(n_test, n_feat), (n_support, n_feat)]
    """
    x_input_shape, xp_input_shape = input_shape  #Unpack

    return input_shape

  def call(self, x_xp, mask=None):
    """Execute this layer on input tensors.

    Parameters
    ----------
    x_xp: list
      List of two tensors (X, Xp). X should be of shape (n_test, n_feat) and
      Xp should be of shape (n_support, n_feat) where n_test is the size of
      the test set, n_support that of the support set, and n_feat is the number
      of per-atom features.

    Returns
    -------
    list
      Returns two tensors of same shape as input. Namely the output shape will
      be [(n_test, n_feat), (n_support, n_feat)]
    """
    # x is test set, xp is support set.
    x, xp = x_xp

    ## Initializes trainable weights.
    n_feat = self.n_feat

    self.lstm = LSTMStep(n_feat, 2 * n_feat)
    self.q_init = model_ops.zeros([self.n_test, n_feat])
    self.r_init = model_ops.zeros([self.n_test, n_feat])
    self.states_init = self.lstm.get_initial_states([self.n_test, n_feat])

    self.trainable_weights = [self.q_init, self.r_init]

    ### Performs computations

    # Get initializations
    q = self.q_init
    #r = self.r_init
    states = self.states_init

    for d in range(self.max_depth):
      # Process using attention
      # Eqn (4), appendix A.1 of Matching Networks paper
      e = cos(x + q, xp)
      a = tf.nn.softmax(e)
      r = model_ops.dot(a, xp)

      # Generate new aattention states
      y = model_ops.concatenate([q, r], axis=1)
      q, states = self.lstm([y] + states)  #+ self.lstm.get_constants(x)

    return [x + q, xp]

  def compute_mask(self, x, mask=None):
    if not (mask is None):
      return mask
    return [None, None]


def cos(x, y):
  denom = (
      model_ops.sqrt(model_ops.sum(tf.square(x)) * model_ops.sum(tf.square(y)))
      + model_ops.epsilon())
  return model_ops.dot(x, tf.transpose(y)) / denom
