"""
PDBBind dataset loader.
"""

from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import os
import numpy as np
import pandas as pd
import shutil
from rdkit import Chem
from deepchem.utils.save import load_from_disk
from deepchem.datasets import DiskDataset
from deepchem.featurizers.fingerprints import CircularFingerprint
from deepchem.transformers import BalancingTransformer
from deepchem.featurizers.nnscore import NNScoreComplexFeaturizer
from deepchem.featurizers.grid_featurizer import GridFeaturizer
from deepchem.featurizers.atomic_coordinates import NeighborListComplexAtomicCoordinates

def load_pdbbind_labels(labels_file):
  """Loads pdbbind labels as dataframe"""
  contents = []
  with open(labels_file) as f:
    for line in f:
      if line.startswith("#"):
        continue
      else:
        contents.append(line.split())
  contents_df = pd.DataFrame(
      contents,
      columns=("PDB code", "resolution", "release year", "-logKd/Ki", "Kd/Ki",
               "ignore-this-field", "reference", "ligand name"))
  return contents_df

def compute_pdbbind_grid_feature(compound_featurizers, complex_featurizers,
                                 pdb_subdir, pdb_code):
  """Compute features for a given complex"""
  protein_file = os.path.join(pdb_subdir, "%s_protein.pdb" % pdb_code)
  ligand_file = os.path.join(pdb_subdir, "%s_ligand.sdf" % pdb_code)
  rdkit_mol = next(Chem.SDMolSupplier(str(ligand_file)))

  all_features = []
  for complex_featurizer in complex_featurizers:
    features = complex_featurizer.featurize_complexes(
      [ligand_file], [protein_file])
    all_features.append(np.squeeze(features))
  
  for compound_featurizer in compound_featurizers:
    features = np.squeeze(compound_featurizer.featurize([rdkit_mol]))
    all_features.append(features)

  features = np.concatenate(all_features)
  return features

def compute_pdbbind_coordinate_features(
    complex_featurizer, pdb_subdir, pdb_code):
  """Compute features for a given complex"""
  protein_file = os.path.join(pdb_subdir, "%s_protein.pdb" % pdb_code)
  ligand_file = os.path.join(pdb_subdir, "%s_ligand.sdf" % pdb_code)

  feature = complex_featurizer.featurize_complexes(
    [ligand_file], [protein_file])
  return feature

def load_core_pdbbind_coordinates(pdbbind_dir, base_dir, reload=True):
  """Load PDBBind datasets. Does not do train/test split"""
  # Set some global variables up top
  reload = True
  verbosity = "high"
  model = "logistic"
  regen = False
  neighbor_cutoff = 4
  max_num_neighbors = 10

  # Create some directories for analysis
  # The base_dir holds the results of all analysis
  if not reload:
    if os.path.exists(base_dir):
      shutil.rmtree(base_dir)
  if not os.path.exists(base_dir):
    os.makedirs(base_dir)
  current_dir = os.path.dirname(os.path.realpath(__file__))
  #Make directories to store the raw and featurized datasets.
  data_dir = os.path.join(base_dir, "dataset")

  # Load PDBBind dataset
  labels_file = os.path.join(pdbbind_dir, "INDEX_core_data.2013")
  pdb_subdirs = os.path.join(pdbbind_dir, "website-core-set")
  tasks = ["-logKd/Ki"]
  print("About to load contents.")
  contents_df = load_pdbbind_labels(labels_file)
  ids = contents_df["PDB code"].values
  y = np.array([float(val) for val in contents_df["-logKd/Ki"].values])

  # Define featurizers
  featurizer = NeighborListComplexAtomicCoordinates(
      max_num_neighbors, neighbor_cutoff)
  
  # Featurize Dataset
  features = []
  for ind, pdb_code in enumerate(ids):
    print("Processing %s" % str(pdb_code))
    pdb_subdir = os.path.join(pdb_subdirs, pdb_code)
    computed_feature = compute_pdbbind_coordinate_features(
        featurizer, pdb_subdir, pdb_code)
    features.append(computed_feature)
  X = np.array(features, dtype-object)
  w = np.ones_like(y)
   
  dataset = DiskDataset.from_numpy(data_dir, X, y, w, ids)
  transformers = []
  
  return tasks, dataset, transformers

def load_core_pdbbind_grid(pdbbind_dir, base_dir, reload=True):
  """Load PDBBind datasets. Does not do train/test split"""
  # Set some global variables up top
  reload = True
  verbosity = "high"
  model = "logistic"
  regen = False

  # Create some directories for analysis
  # The base_dir holds the results of all analysis
  if not reload:
    if os.path.exists(base_dir):
      shutil.rmtree(base_dir)
  if not os.path.exists(base_dir):
    os.makedirs(base_dir)
  current_dir = os.path.dirname(os.path.realpath(__file__))
  #Make directories to store the raw and featurized datasets.
  data_dir = os.path.join(base_dir, "dataset")

  # Load PDBBind dataset
  labels_file = os.path.join(pdbbind_dir, "INDEX_core_data.2013")
  pdb_subdirs = os.path.join(pdbbind_dir, "website-core-set")
  tasks = ["-logKd/Ki"]
  print("About to load contents.")
  contents_df = load_pdbbind_labels(labels_file)
  ids = contents_df["PDB code"].values
  y = np.array([float(val) for val in contents_df["-logKd/Ki"].values])

  # Define featurizers
  grid_featurizer = GridFeaturizer(
      voxel_width=16.0, feature_types="voxel_combined",
      # TODO(rbharath, enf): Figure out why pi_stack is slow and cation_pi
      # causes segfaults.
      #voxel_feature_types=["ecfp", "splif", "hbond", "pi_stack", "cation_pi",
      #"salt_bridge"], ecfp_power=9, splif_power=9,
      voxel_feature_types=["ecfp", "splif", "hbond", 
      "salt_bridge"], ecfp_power=9, splif_power=9,
      parallel=True, flatten=True,
      verbosity=verbosity)
  compound_featurizers = [CircularFingerprint(size=1024)]
  complex_featurizers = [grid_featurizer]
  
  # Featurize Dataset
  features = []
  feature_len = None
  y_inds = []
  for ind, pdb_code in enumerate(ids):
    print("Processing %s" % str(pdb_code))
    pdb_subdir = os.path.join(pdb_subdirs, pdb_code)
    computed_feature = compute_pdbbind_grid_feature(
        compound_featurizers, complex_featurizers, pdb_subdir, pdb_code)
    if feature_len is None:
      feature_len = len(computed_feature)
    if len(computed_feature) != feature_len:
      print("Featurization failed for %s!" % pdb_code)
      continue
    y_inds.append(ind)
    features.append(computed_feature)
  y = y[y_inds]
  X = np.vstack(features)
  w = np.ones_like(y)
   
  dataset = DiskDataset.from_numpy(data_dir, X, y, w, ids)
  transformers = []
  
  return tasks, dataset, transformers
