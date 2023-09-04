"""
Utility Functions for computing features on batch.
"""
import numpy as np
from typing import Any, Dict, List


def batch_coulomb_matrix_features(X_b: np.ndarray,
                                  distance_max: float = -1,
                                  distance_min: float = 18,
                                  n_distance: int = 100):
    """Computes the values for different Feature on given batch.
    It works as a helper function to coulomb matrix.

    This function takes in a batch of Molecules represented as Coulomb Matrix.

    It proceeds as follows:

    - It calculates the Number of atoms per molecule by counting all the non zero elements(numbers) of every\
    molecule layer in matrix in one dimension.

    - The Gaussian distance is calculated using the Euclidean distance between the Cartesian coordinates of two atoms.\
    The distance value is then passed through a Gaussian function, which transforms it into a continuous value.

    - Then using number of atom per molecule, calculates the atomic charge by looping over the molecule layer in the Coulomb matrix\
    and takes the `2.4` root of the diagonal of `2X` of each molecule layer. `Undoing the Equation of coulomb matrix.`

    - Atom_membership is assigned as a commomn repeating integers for all the atoms for a specific molecule.

    - Distance Membership encodes spatial information, assigning closer values to atoms that are in that specific molecule.\
    All initial Distances are added a start value to them which are unique to each molecule.

    Models Used in:

    * DTNN

    Parameters
    ----------
    X_b: np.ndarray
        It is a 3d Matrix containing information of each the atom's ionic interaction with other atoms in the molecule.
    distance_min: float (default -1)
        minimum distance of atom pairs (in Angstrom)
    distance_max: float (default = 18)
        maximum distance of atom pairs (in Angstrom)
    n_distance: int (default 100)
        granularity of distance matrix
        step size will be (distance_max-distance_min)/n_distance

    Returns
    -------
    atom_number: np.ndarray
        Atom numbers are assigned to each atom based on their atomic properties.
        The atomic numbers are derived from the periodic table of elements.
        For example, hydrogen -> 1, carbon -> 6, and oxygen -> 8.
    gaussian_dist: np.ndarray
        Gaussian distance refers to the method of representing the pairwise distances between atoms in a molecule using Gaussian functions.
        The Gaussian distance is calculated using the Euclidean distance between the Cartesian coordinates of two atoms.
        The distance value is then passed through a Gaussian function, which transforms it into a continuous value.
    atom_mem: np.ndarray
        Atom membership refers to the binary representation of whether an atom belongs to a specific group or property within a molecule.
        It allows the model to incorporate domain-specific information and enhance its understanding of the molecule's properties and interactions.
    dist_mem_i: np.ndarray
        Distance membership i are utilized to encode spatial information and capture the influence of atom distances on the properties and interactions within a molecule.
        The inner membership function assigns higher values to atoms that are closer to the atoms' interaction region, thereby emphasizing the impact of nearby atoms.
    dist_mem_j: np.ndarray
        It captures the long-range effects and influences between atoms that are not in direct proximity but still contribute to the overall molecular properties.
        Distance membership j are utilized to encode spatial information and capture the influence of atom distances on the properties and interactions outside a molecule.
        The outer membership function assigns higher values to atoms that are farther to the atoms' interaction region, thereby emphasizing the impact of farther atoms.

    Examples
    --------
    >>> import os
    >>> import deepchem as dc
    >>> current_dir = os.path.dirname(os.path.abspath(__file__))
    >>> dataset_file = os.path.join(current_dir, 'test/assets/qm9_mini.sdf')
    >>> TASKS = ["alpha", "homo"]
    >>> loader = dc.data.SDFLoader(tasks=TASKS,
    ...                            featurizer=dc.feat.CoulombMatrix(29),
    ...                            sanitize=True)
    >>> data = loader.create_dataset(dataset_file, shard_size=100)
    >>> inputs = dc.utils.batch_utils.batch_coulomb_matrix_features(data.X)

    References
    ----------
    .. [1] Montavon, Grégoire, et al. "Learning invariant representations of
        molecules for atomization energy prediction." Advances in neural information
        processing systems. 2012.

    """
    distance = []
    atom_membership = []
    distance_membership_i = []
    distance_membership_j = []

    # Calculation of Step Size and steps
    step_size = (distance_max - distance_min) / n_distance
    steps = np.array([distance_min + i * step_size for i in range(n_distance)])
    steps = np.expand_dims(steps, 0)

    # Number of atoms per molecule is calculated by counting all the non zero elements(numbers) of every molecule.
    num_atoms = list(map(sum, X_b.astype(bool)[:, :, 0]))

    # It loops over the molecules in the Coulomb matrix and takes the "2.4" root of the diagonal of "2X" of each molecule's representation.
    atom_number = [
        np.round(
            np.power(2 * np.diag(X_b[i, :num_atoms[i], :num_atoms[i]]),
                     1 / 2.4)).astype(int) for i in range(len(num_atoms))
    ]
    start = 0
    for im, molecule in enumerate(atom_number):
        distance_matrix = np.outer(
            molecule, molecule) / X_b[im, :num_atoms[im], :num_atoms[im]]
        np.fill_diagonal(distance_matrix, -100)
        distance.append(np.expand_dims(distance_matrix.flatten(), 1))
        atom_membership.append([im] * num_atoms[im])
        membership = np.array([np.arange(num_atoms[im])] * num_atoms[im])
        membership_i = membership.flatten(order='F')
        membership_j = membership.flatten()
        distance_membership_i.append(membership_i + start)
        distance_membership_j.append(membership_j + start)
        start = start + num_atoms[im]
    atom_number = np.concatenate(atom_number).astype(np.int32)
    distance = np.concatenate(distance, axis=0)

    # Calculates the Gaussian Distance by passing distance by a gaussian function.
    gaussian_dist = np.exp(-np.square(distance - steps) / (2 * step_size**2))
    gaussian_dist = gaussian_dist.astype(np.float64)
    atom_mem = np.concatenate(atom_membership).astype(np.int64)
    dist_mem_i = np.concatenate(distance_membership_i).astype(np.int64)
    dist_mem_j = np.concatenate(distance_membership_j).astype(np.int64)
    features = [atom_number, gaussian_dist, atom_mem, dist_mem_i, dist_mem_j]
    return features


def batch_elements(elements: Any, batch_size: int):
    """Combine elements into batches.
    
    Parameters
    ----------
    elements: Any
        Elements to be combined into batches.
    batch_size: int
        Batch size in which to divide.

    Returns
    -------
    batch: Any
        Batch of elements.

    """
    batch = []
    for s in elements:
        batch.append(s)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if len(batch) > 0:
        yield batch


def create_input_array(sequences: List,
                       reverse_input: bool,
                       batch_size: int,
                       input_dict: Dict,
                       end_mark: Any):
    """Create the array describing the input sequences for a batch.
    
    It creates a 2d Matrix empty matrix according to batch size and max_length.
    Then iteratively fills it with the key-values from the input dictionary.

    These values can be used to generate embeddings for further processing.

    Models used in:

    * SeqToSeq

    Parameters
    ----------
    sequences: list
        List of sequences to be converted into input array.
    reverse_input: bool
        If True, reverse the order of input sequences before sending them into
        the encoder. This can improve performance when working with long sequences.
    batch_size: int
        Batch size of the input array.
    input_dict: dict
        Dictionary containing the key-value pairs of input sequences.
    end_mark: Any
        End mark for the input sequences.

    """
    lengths = [len(x) for x in sequences]
    if reverse_input:
        sequences = [reversed(s) for s in sequences]
    features = np.zeros((batch_size, max(lengths) + 1), dtype=np.float32)
    for i, sequence in enumerate(sequences):
        for j, token in enumerate(sequence):
            features[i, j] = input_dict[token]
    features[np.arange(len(sequences)), lengths] = input_dict[end_mark]
    return features


def create_output_array(sequences, max_output_length, batch_size, output_dict, end_mark):
    """Create the array describing the target sequences for a batch."""
    lengths = [len(x) for x in sequences]
    labels = np.zeros((batch_size, max_output_length), dtype=np.float32)
    for i, sequence in enumerate(sequences):
        for j, token in enumerate(sequence):
            labels[i, j] = output_dict[token]
        for j in range(lengths[i], max_output_length):
            labels[i, j] = output_dict[end_mark]
    return labels


def generate_batches(sequences,
                     model,
                     max_output_length: int,
                     reverse_input: bool,
                     batch_size: int,
                     input_dict: Dict,
                     output_dict: Dict,
                     end_mark):
    """Create feed_dicts for fitting."""
    for batch in batch_elements(sequences):
        inputs = []
        outputs = []
        for input, output in batch:
            inputs.append(input)
            outputs.append(output)
        for i in range(len(inputs), batch_size):
            inputs.append([])
            outputs.append([])
        features = create_input_array(inputs, reverse_input, batch_size, input_dict, end_mark)
        labels = create_output_array(outputs, max_output_length, batch_size, output_dict, end_mark)
        yield ([features, np.array(model.get_global_step())], [labels], [])
