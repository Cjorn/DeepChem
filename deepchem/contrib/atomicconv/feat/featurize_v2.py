__author__ = "Joseph Gomes"
__copyright__ = "Copyright 2016, Stanford University"
__license__ = "MIT"

import os
import sys
from subprocess import call

import numpy as np
import pandas as pd
from rdkit import Chem

from deepchem.feat import Featurizer
from deepchem.feat import ComplexFeaturizer
from deepchem.utils import pad_array
import deepchem as dc

def get_cells(coords, neighbor_cutoff):
  """Computes cells given molecular coordinates.

  Parameters
  ----------
  coords: np.array
    Cartesian coordaintes [Angstrom]
  neighbor_cutoff: float
    Threshold distance [Angstroms] for counting neighbors.
    
  Returns
  -------
  x_bins: list
    List contains tuples of x_cell boundaries
  y_bins: list
    List contains tuples of y_cell boundaries
  z_bins: list
    List contains tuples of z_cell boundaries

  """

  x_max, x_min = np.amax(coords[:, 0]), np.amin(coords[:, 0])
  y_max, y_min = np.amax(coords[:, 1]), np.amin(coords[:, 1])
  z_max, z_min = np.amax(coords[:, 2]), np.amin(coords[:, 2])

  # Compute cells for this molecule. O(constant)
  x_bins, y_bins, z_bins = [], [], []
  x_current, y_current, z_current = x_min, y_min, z_min
  # min == max if molecule is planar in some direction
  # we should still create a bin
  if not x_min == x_max:
    while x_current < x_max:
      x_bins.append((x_current, x_current + neighbor_cutoff))
      x_current += neighbor_cutoff
  else:
    x_bins.append((x_current, x_current + neighbor_cutoff))
  if not y_min == y_max:
    while y_current < y_max:
      y_bins.append((y_current, y_current + neighbor_cutoff))
      y_current += neighbor_cutoff
  else:
    y_bins.append((y_current, y_current + neighbor_cutoff))
  if not z_min == z_max:
    while z_current < z_max:
      z_bins.append((z_current, z_current + neighbor_cutoff))
      z_current += neighbor_cutoff
  else:
    z_bins.append((z_current, z_current + neighbor_cutoff))
  return x_bins, y_bins, z_bins


def put_atoms_in_cells(coords, x_bins, y_bins, z_bins):
  """Place each atom into cells. O(N) runtime.
  
  Parameters
  ----------
  coords: np.ndarray
    (N, 3) array where N is number of atoms
  x_bins: list
    List of (cell_start, cell_end) for x-coordinate
  y_bins: list
    List of (cell_start, cell_end) for y-coordinate
  z_bins: list
    List of (cell_start, cell_end) for z-coordinate

  Returns
  -------
  cell_to_atoms: dict
    Dict elements contain atom indices for cell
  atom_to_cell: dict
    Dict elements contain cell indices for atom

  """

  N = coords.shape[0]
  cell_to_atoms = {}
  atom_to_cell = {}
  for x_ind in range(len(x_bins)):
    for y_ind in range(len(y_bins)):
      for z_ind in range(len(z_bins)):
        cell_to_atoms[(x_ind, y_ind, z_ind)] = []
  for atom in range(N):
    x_coord, y_coord, z_coord = coords[atom]
    x_ind, y_ind, z_ind = None, None, None
    for ind, (x_cell_min, x_cell_max) in enumerate(x_bins):
      if x_coord >= x_cell_min and x_coord <= x_cell_max:
        x_ind = ind
        break
    if x_ind is None:
      raise ValueError("No x-cell found!")
    for ind, (y_cell_min, y_cell_max) in enumerate(y_bins):
      if y_coord >= y_cell_min and y_coord <= y_cell_max:
        y_ind = ind
        break
    if y_ind is None:
      raise ValueError("No y-cell found!")
    for ind, (z_cell_min, z_cell_max) in enumerate(z_bins):
      if z_coord >= z_cell_min and z_coord <= z_cell_max:
        z_ind = ind
        break
    if z_ind is None:
      raise ValueError("No z-cell found!")
    cell_to_atoms[(x_ind, y_ind, z_ind)].append(atom)
    atom_to_cell[atom] = (x_ind, y_ind, z_ind)
  return cell_to_atoms, atom_to_cell


def compute_neighbor_cell_map(N_x, N_y, N_z):
  """Compute neighbors of cells in grid.
  
  Parameters
  ----------
  N_x: int
    Number of grid cells in x-dimension.
  N_y: int
    Number of grid cells in y-dimension.
  N_z: int
    Number of grid cells in z-dimension.

  Returns
  -------
  neighbor_cell_map: dict
    Dict elements contain neighbor cell indices

  """

  #TODO(JSG): Implement non-PBC version.  For now this seems fine ..
  neighbor_cell_map = {}
  for x_ind in range(N_x):
    for y_ind in range(N_y):
      for z_ind in range(N_z):
        neighbors = []
        offsets = [-1, 0, +1]
        # Note neighbors contains self!
        for x_offset in offsets:
          for y_offset in offsets:
            for z_offset in offsets:
              neighbors.append(
                  ((x_ind + x_offset) % N_x, (y_ind + y_offset) % N_y,
                   (z_ind + z_offset) % N_z))
        neighbor_cell_map[(x_ind, y_ind, z_ind)] = neighbors
  return neighbor_cell_map


def get_coords(mol):
  """Gets coordinates in Angstrom for RDKit mol.

  Parameters
  ----------
  mol: rdkit.Chem.rdchem.mol
    Molecule
  
  Returns
  -------
  coords: np.array
    Cartestian coordinates [Angstrom]

  """

  N = mol.GetNumAtoms()
  coords = np.zeros((N, 3))

  coords_raw = [mol.GetConformer(0).GetAtomPosition(i) for i in range(N)]
  for atom in range(N):
    coords[atom, 0] = coords_raw[atom].x
    coords[atom, 1] = coords_raw[atom].y
    coords[atom, 2] = coords_raw[atom].z
  return coords


class NeighborListAtomicCoordinates(Featurizer):
  """
  Adjacency List of neighbors in 3-space
  Neighbors determined by user-defined distance cutoff [in Angstrom].

  https://en.wikipedia.org/wiki/Cell_list
  Ref: http://www.cs.cornell.edu/ron/references/1989/Calculations%20of%20a%20List%20of%20Neighbors%20in%20Molecular%20Dynamics%20Si.pdf

  Example:

  >>> n_atoms = 6
  >>> n_neighbors = 6
  >>> cutoff = 12.0
  >>> boxsize = None
  >>> input_file = "test.sdf"
  >>> tasks = ["energy"]
  >>> featurizers = NeighborListAtomicCoordinates(n_atoms, n_neighbors, cutoff, boxsize)
  >>> featurizer = dc.data.SDFLoader(tasks, smiles_field="smiles", mol_field="mol",
                      featurizer=featurizers)
  >>> dataset = featurizer.featurize(input_file) 

  """

  def __init__(self,
               max_num_atoms,
               max_num_neighbors,
               neighbor_cutoff,
               boxsize=None):
    """Initialize NeighborListAtomicCoordinates featurizer.

    Parameters
    ----------
    max_num_atoms: int
      Maximum number of atoms.
    max_num_neighbors: int
      Maximum number of neighbors per atom.
    neighbor_cutoff: float
      Threshold distance [Angstroms] for counting neighbors.
    boxsize: float, optional (default None)
      Size of periodic box. If None, no periodic boundary conditions.

    """
    if boxsize is not None and boxsize < 2 * neighbor_cutoff:
      raise ValueError("boxsize must be greater than 2*neighbor_cutoff")
    self.max_num_atoms = max_num_atoms
    self.max_num_neighbors = max_num_neighbors
    self.neighbor_cutoff = neighbor_cutoff
    self.boxsize = boxsize
    self.dtype = object

  def _featurize(self, mol):
    """Compute neighbor list.

    Parameters
    ----------
    mol: rdkit.Chem.rdchem.mol
      Molecule

    """
    N = mol.GetNumAtoms()
    coords = get_coords(mol)

    x_bins, y_bins, z_bins = get_cells(coords, self.neighbor_cutoff)

    # Associate each atom with cell it belongs to. O(N)
    cell_to_atoms, atom_to_cell = put_atoms_in_cells(coords, x_bins, y_bins,
                                                     z_bins)

    # Associate each cell with its neighbor cells. Assumes periodic boundary
    # conditions, so does wrapround. O(constant)
    N_x, N_y, N_z = len(x_bins), len(y_bins), len(z_bins)
    neighbor_cell_map = compute_neighbor_cell_map(N_x, N_y, N_z)

    # For each atom, loop through all atoms in its cell and neighboring cells.
    # Accept as neighbors only those within threshold. This computation should be
    # O(Nm), where m is the number of atoms within a set of neighboring-cells.
    neighbor_list = {}
    if self.boxsize is not None:
      for atom in range(N):
        cell = atom_to_cell[atom]
        neighbor_cells = neighbor_cell_map[cell]
        neighbor_list[atom] = set()
        for neighbor_cell in neighbor_cells:
          atoms_in_cell = cell_to_atoms[neighbor_cell]
          for neighbor_atom in atoms_in_cell:
            if neighbor_atom == atom:
              continue
            dist = np.linalg.norm(coords[atom] - coords[neighbor_atom])
            dist = dist - self.boxsize * np.round(dist / self.boxsize)
            if dist < self.neighbor_cutoff:
              neighbor_list[atom].add((neighbor_atom, dist))
        # Sort neighbors by distance
        closest_neighbors = sorted(
            list(neighbor_list[atom]), key=lambda elt: elt[1])
        closest_neighbors = [nbr for (nbr, dist) in closest_neighbors]
        # Pick up to max_num_neighbors
        closest_neighbors = closest_neighbors[:self.max_num_neighbors]
        neighbor_list[atom] = closest_neighbors
    else:
      for atom in range(N):
        cell = atom_to_cell[atom]
        neighbor_cells = neighbor_cell_map[cell]
        neighbor_list[atom] = set()
        for neighbor_cell in neighbor_cells:
          atoms_in_cell = cell_to_atoms[neighbor_cell]
          for neighbor_atom in atoms_in_cell:
            if neighbor_atom == atom:
              continue
            dist = np.linalg.norm(coords[atom] - coords[neighbor_atom])
            if dist < self.neighbor_cutoff:
              neighbor_list[atom].add((neighbor_atom, dist))
        closest_neighbors = sorted(
            list(neighbor_list[atom]), key=lambda elt: elt[1])
        closest_neighbors = [nbr for (nbr, dist) in closest_neighbors]
        closest_neighbors = closest_neighbors[:self.max_num_neighbors]
        neighbor_list[atom] = closest_neighbors
    Z = pad_array(
        np.array([atom.GetAtomicNum()
                  for atom in mol.GetAtoms()]), self.max_num_atoms)
    coords = pad_array(coords, (self.max_num_atoms, 3))
    return (coords, neighbor_list, Z)


class ComplexNeighborListFragmentAtomicCoordinates(ComplexFeaturizer):
  """
  Adjacency list of neighbors for protein-ligand complexes in 3-space.
  Neighbors dtermined by user-defined distance cutoff.
  Currently only compatible with pdb files.

  Example:

  >>> frag1_n_atoms = 3
  >>> frag2_n_atoms = 3
  >>> complex_n_atoms = 6
  >>> n_neighbors = 6
  >>> cutoff = 12.0
  >>> boxsize = None
  >>> featurizer = ComplexNeighborListFragmentAtomicCoordinates(frag1_n_atoms,
                    frag2_n_atoms, complex_n_atoms, n_neighbors, cutoff, boxsize)
  >>> frag1 = "frag1.pdb"
  >>> frag2 = "frag2.pdb"
  >>> feature = featurizer._featurize_complex(str(frag1), str(frag2))

  """

  def __init__(self,
               frag1_num_atoms,
               frag2_num_atoms,
               complex_num_atoms,
               max_num_neighbors,
               neighbor_cutoff=12.0,
               boxsize=None):
    """Initialize ComplexNeighborListFragmentAtomicCoordinates featurizer

    Parameters
    ----------
    frag1_num_atoms: int
      Maximum number of atoms in frag1
    frag2_num_atoms: int
      Maximum number of atoms in frag2
    complex_num_atoms: int
      Maximum number of atoms in complex
    max_num_neighbors: int
      Maximum number of neighbors per atom
    neighbor_cutoff: float
      Threshold distance [Angstroms] for counting neighbors.
    boxsize: float, optional (default None)
      Size of periodic box. If None, no periodic boundary conditions.

    """

    self.frag1_num_atoms = frag1_num_atoms
    self.frag2_num_atoms = frag2_num_atoms
    self.complex_num_atoms = complex_num_atoms
    self.max_num_neighbors = max_num_neighbors
    self.neighbor_cutoff = neighbor_cutoff
    self.boxsize = boxsize
    # Type of data created by this featurizer
    self.dtype = object
    self.frag1_featurizer = NeighborListAtomicCoordinates(
        self.frag1_num_atoms, self.max_num_neighbors, self.neighbor_cutoff,
        self.boxsize)
    self.frag2_featurizer = NeighborListAtomicCoordinates(
        self.frag2_num_atoms, self.max_num_neighbors, self.neighbor_cutoff,
        self.boxsize)
    self.complex_featurizer = NeighborListAtomicCoordinates(
        self.complex_num_atoms, self.max_num_neighbors, self.neighbor_cutoff,
        self.boxsize)

  def _featurize_complex(self, frag1_pdb_file, frag2_pdb_file):
    """Featurize fragments and complex.

    Parameters
    ----------
    frag1_pdb_file: string
      Location of frag1_pdb_file.
    frag2_pdb_file: string
      Location of frag2_pdb_file.

    Returns
    -------
    retval: tuple
      Tuple containing coordinates, neighbor list, and atomic number for
      fragment 1, fragment 2, and complex

    """

    try:
      frag1_mol = Chem.MolFromPDBFile(
          frag1_pdb_file, sanitize=False, removeHs=False)
      frag2_mol = Chem.MolFromPDBFile(
          frag2_pdb_file, sanitize=False, removeHs=False)
    except:
      frag1_mol = None
      frag2_mol = None
    if frag1_mol and frag2_mol:
      frag1_coords, frag1_neighbor_list, frag1_z = self.frag1_featurizer._featurize(
          frag1_mol)
      frag2_coords, frag2_neighbor_list, frag2_z = self.frag2_featurizer._featurize(
          frag2_mol)
      complex_mol = Chem.rdmolops.CombineMols(frag1_mol, frag2_mol)
      complex_coords, complex_neighbor_list, complex_z = self.complex_featurizer._featurize(
          complex_mol)
      return (frag1_coords, frag1_neighbor_list, frag1_z, frag2_coords,
              frag2_neighbor_list, frag2_z, complex_coords,
              complex_neighbor_list, complex_z)
    else:
      print("failed to featurize")
      return (None, None, None, None, None, None, None, None, None)



def load_pdbbind_labels(labels_file):
  """Loads pdbbind labels as dataframe

  Parameters
  ----------
  labels_file: str
    Location of PDBbind datafile.

  Returns
  -------
  contents_df: pd.DataFrame
    Dataframe containing contents of PDBbind datafile.

  """

  contents = []
  with open(labels_file) as f:
    for line in f:
      if line.startswith("#"):
        continue
      else:
        splitline = line.split()
        if len(splitline) == 8:
          contents.append(splitline)
        else:
          print("Incorrect data format")
          print(splitline)

  contents_df = pd.DataFrame(
      contents,
      columns=("PDB code", "resolution", "release year", "-logKd/Ki", "Kd/Ki",
               "ignore-this-field", "reference", "ligand name"))
  return contents_df


def compute_pdbbind_coordinate_features(complex_featurizer, pdb_subdir,
                                        pdb_code):
  """Compute features for a given complex

  Parameters
  ----------
  complex_featurizer: dc.feat.ComplexFeaturizer
    Complex featurizer.
  pdb_subdir: str
    Location of complex PDB files.
  pdb_core: str
    Complex PDB code.

  Returns
  -------
  feature: Tuple
    Complex features.

  """

  protein_file = os.path.join(pdb_subdir, "%s_pocket.pdb" % pdb_code)
  ligand_file = os.path.join(pdb_subdir, "%s_ligand.pdb" % pdb_code)
  feature = complex_featurizer._featurize_complex(
      str(ligand_file), str(protein_file))
  return feature


def load_pdbbind_fragment_coordinates(frag1_num_atoms,
                                      frag2_num_atoms,
                                      complex_num_atoms,
                                      max_num_neighbors,
                                      neighbor_cutoff,
                                      pdbbind_dir,
                                      base_dir,
                                      datafile="INDEX_core_data.2013"):
  """Featurize PDBBind dataset.

  Parameters
  ----------
  frag1_num_atoms: int
    Maximum number of atoms in fragment 1.
  frag2_num_atoms: int
    Maximum number of atoms in fragment 2.
  complex_num_atoms: int
    Maximum number of atoms in complex.
  max_num_neighbors: int
    Maximum number of neighbors per atom.
  neighbor_cutoff: float
    Interaction cutoff [Angstrom].
  pdbbind_dir: str
    Location of PDBbind datafile.
  base_dir: str
    Location for storing featurized dataset.
  datafile: str
    Name of PDBbind datafile, optional (Default "INDEX_core_data.2013").

  Returns
  -------
  tasks: list
    PDBbind tasks.
  dataset: dc.data.DiskDataset
    PDBbind featurized dataset.
  transformers: list
    dc.trans.Transformer objects.

  """

  # Create some directories for analysis
  # The base_dir holds the results of all analysis
#  if not reload:
#    if os.path.exists(base_dir):
#      shutil.rmtree(base_dir)
  if not os.path.exists(base_dir):
    os.makedirs(base_dir)
  current_dir = os.path.dirname(os.path.realpath(__file__))
  #Make directories to store the raw and featurized datasets.
  data_dir = os.path.join(base_dir, "dataset")

  # Load PDBBind dataset
  labels_file = os.path.join(pdbbind_dir, datafile)
  tasks = ["-logKd/Ki"]
  print("About to load contents.")
  contents_df = load_pdbbind_labels(labels_file)
  ids = contents_df["PDB code"].values
  y = np.array([float(val) for val in contents_df["-logKd/Ki"].values])

  # Define featurizers
  featurizer = ComplexNeighborListFragmentAtomicCoordinates(
      frag1_num_atoms, frag2_num_atoms, complex_num_atoms, max_num_neighbors,
      neighbor_cutoff)

  w = np.ones_like(y)

  #Currently featurizes with shard_size=1
  #Dataset can be reshard: dataset = dataset.reshard(48) for example
  def shard_generator():
    for ind, pdb_code in enumerate(ids):
      print("Processing %s" % str(pdb_code))
      pdb_subdir = os.path.join(pdbbind_dir, pdb_code)
      computed_feature = compute_pdbbind_coordinate_features(
          featurizer, pdb_subdir, pdb_code)
      if computed_feature[0] is None:
        print("Bad featurization")
        continue
      else:
        X_b = np.reshape(np.array(computed_feature), (1, 9))
        y_b = y[ind]
        w_b = w[ind]
        y_b = np.reshape(y_b, (1, -1))
        w_b = np.reshape(w_b, (1, -1))
        yield (X_b, y_b, w_b, pdb_code)

  dataset = dc.data.DiskDataset.create_dataset(
      shard_generator(), data_dir=data_dir, tasks=tasks)
  transformers = []
  
  #dataset = dataset.reshard(48)

  return tasks, dataset, transformers


#################

DATA_DIR = '/Users/staker/Projects/external/deepchem/contrib/atomicconv/feat/v2015'

if False:
        # TODO: Build checker to see if files exist, if not, run these
    call([
        "wget",
        "http://deepchem.io.s3-website-us-west-1.amazonaws.com/datasets/pdbbind_v2015.tar.gz"
    ])
    call(["tar", "-xvzf", "pdbbind_v2015.tar.gz"])

    # This could be done with openbabel in python
    call(["convert_ligand_sdf_to_pdb.sh"])

    base_dir = os.getcwd()
    pdbbind_dir = os.path.join(base_dir, "v2015")

base_dir = os.getcwd()
pdbbind_dir = DATA_DIR
datafile = "INDEX_core_data.2013"

frag1_num_atoms = 140
frag2_num_atoms = 821
complex_num_atoms = 908
max_num_neighbors = 8
neighbor_cutoff = 12.0

pdbbind_tasks, dataset, transformers = load_pdbbind_fragment_coordinates(
    frag1_num_atoms, frag2_num_atoms, complex_num_atoms, max_num_neighbors,
    neighbor_cutoff, pdbbind_dir, base_dir, datafile)





