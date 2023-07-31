"""
Implementation of the Ferminet class in pytorch
"""

from typing import List, Optional
# import torch.nn as nn
from rdkit import Chem
import numpy as np
from deepchem.utils.molecule_feature_utils import ALLEN_ELECTRONEGATIVTY
from deepchem.utils.geometry_utils import compute_pairwise_distances
from deepchem.models.torch_models import TorchModel
from deepchem.models.losses import L2Loss
import deepchem.models.optimizers as optimizers
import torch
from torch import nn

from deepchem.utils.electron_sampler import ElectronSampler

# TODO look for the loss function(Hamiltonian)


def test_f(x: np.ndarray) -> np.ndarray:
    # dummy function which can be passed as the parameter f. f gives the log probability
    # TODO replace this function with forward pass of the model in future
    return 2 * np.log(np.random.uniform(low=0, high=1.0, size=np.shape(x)[0]))


class Ferminet(torch.nn.Module):
    """Approximates the log probability of the wave function of a molecule system using DNNs.
    """

    def __init__(self,
               nucleon_pos: torch.tensor,
               nuclear_charge: torch.tensor,
               spin: tuple,
               n_one: List = [256, 256, 256, 256],
               n_two: List = [32, 32, 32, 32],
               determinant: int = 16,
               batch_size:int = 8) -> None:
        """
        Parameters:
        -----------
        n_one: List
            List of hidden units for the one-electron stream in each layer
        n_two: List
            List of hidden units for the two-electron stream in each layer
        determinant: int
            Number of determinants for the final solution
        """
        super(Ferminet, self).__init__()
        if len(n_one) != len(n_two):
            raise ValueError(
              "The number of layers in one-electron and two-electron stream should be equal"
        )
        else:
            self.layers = len(n_one)

        self.nucleon_pos = nucleon_pos
        self.determinant = determinant
        self.batch_size = batch_size
        self.spin = spin
        self.total_electron = spin[0] + spin[1]
        self.nuclear_charge = nuclear_charge
        self.v = nn.ModuleList()
        self.w = nn.ModuleList()
        self.envelope_w = nn.ParameterList()
        self.envelope_g = nn.ParameterList()
        self.sigma = nn.ParameterList()
        self.pi = nn.ParameterList()
        self.n_one = n_one
        self.n_two = n_two

        self.v.append(nn.Linear(8+3*4*self.nucleon_pos.size()[0],n_one[0],bias=True))
        self.w.append(nn.Linear(4,n_two[0],bias=True))
        for i in range(1,self.layers):
            self.v.append(nn.Linear(3*n_one[i-1]+2*n_two[i-1],n_one[i],bias=True))
            self.w.append(nn.Linear(n_two[i-1],n_two[i],bias=True))

        for i in range(self.determinant):
            for j in range(self.total_electron):
                self.envelope_w.append(torch.nn.init.kaiming_uniform(torch.empty(n_one[-1],1)).squeeze(-1))
                self.envelope_g.append(torch.nn.init.uniform(torch.empty(1)).squeeze(0))
                for k in range(self.nucleon_pos.size()[0]):
                    self.sigma.append(torch.nn.init.uniform(torch.empty(self.nucleon_pos.size()[0],1)).squeeze(0))
                    self.pi.append(torch.nn.init.uniform(torch.empty(self.nucleon_pos.size()[0],1)).squeeze(0))

    def forward(self, input):
        # creating one and two electron features
        self.input = torch.from_numpy(input)
        self.input.requires_grad = True
        self.input = self.input.reshape((self.batch_size, -1, 3))
        two_electron_vector = self.input.unsqueeze(1) - self.input.unsqueeze(2)
        two_electron_distance = torch.norm(two_electron_vector, dim=3).unsqueeze(3)
        two_electron = torch.cat((two_electron_vector, two_electron_distance), dim=3)
        two_electron = torch.reshape(two_electron,(self.batch_size, self.total_electron,self.total_electron,-1))


        one_electron_vector = self.input.unsqueeze(1) - self.nucleon_pos.unsqueeze(1)
        one_electron_distance = torch.norm(one_electron_vector, dim=3)
        one_electron = torch.cat((one_electron_vector, one_electron_distance.unsqueeze(-1)),dim=3)
        one_electron = torch.reshape(one_electron.permute(0,2,1,3),(self.batch_size, self.total_electron, -1))
        one_electron_vector_permuted = one_electron_vector.permute(0,2,1,3)

        for l in range(len(self.n_one)):
            g_one_up = torch.mean(one_electron[:,:self.spin[0],:],dim=-2)
            g_one_down = torch.mean(one_electron[:,self.spin[0]:,:],dim=-2)
            one_electron_tmp = torch.zeros(self.batch_size, self.total_electron,  self.n_one[l])
            two_electron_tmp = torch.zeros(self.batch_size, self.total_electron, self.total_electron, self.n_two[l])
            for i in range(self.total_electron):
                g_two_up = torch.mean(two_electron[:,i,:self.spin[0],:],dim=1)
                g_two_down = torch.mean(two_electron[:,i,self.spin[0]:,:],dim=1)
                f = torch.cat((one_electron[:,i,:],g_one_up,g_one_down,g_two_up,g_two_down),dim=1)
                if l==0 or (self.n_one[l]!=self.n_one[l-1]) or (self.n_two[l]!=self.n_two[l-1]):
                    one_electron_tmp[:,i,:] = torch.tanh(self.v[l](f.to(torch.float32)))
                    two_electron_tmp[:,i,:,:] = torch.tanh(self.w[l](two_electron[:,i,:,:].to(torch.float32)))
                else:
                    one_electron_tmp[:,i,:] = torch.tanh(self.v[l](f.to(torch.float32))) + one_electron[:,i,:].to(torch.float32)
                    two_electron_tmp[:,i,:,:] = torch.tanh(self.w[l](two_electron[:,i,:,:].to(torch.float32))) + two_electron[:,i,:].to(torch.float32)
            one_electron = one_electron_tmp
            two_electron = two_electron_tmp

        psi = torch.zeros(self.batch_size)
        psi_up = torch.zeros(self.batch_size, self.determinant, self.spin[0], self.spin[0])
        psi_down = torch.zeros(self.batch_size, self.determinant, self.spin[1], self.spin[1])
        #psi_up.requires_grad = True
        #psi_down.requires_grad =  True
        for k in range(self.determinant):
            for i in range(self.spin[0]):
                one_d_index = (k * (self.total_electron)) + i
                for j in range(self.spin[0]):
                    psi_up[:,k,i,j]=(torch.sum((self.envelope_w[one_d_index]*one_electron[:,j,:])+self.envelope_g[one_d_index],dim=1))*torch.sum(
                        torch.exp(-torch.abs(torch.norm(self.sigma[one_d_index]*one_electron_vector_permuted[:,j,:,:],dim=2
                                                               )))*self.pi[one_d_index].T,dim=1)

            for i in range(self.spin[1]):
                one_d_index = (k * (self.total_electron)) + i
                for j in range(self.spin[0],self.spin[0]+self.spin[1]):
                    psi_down[:,k,i,j-self.spin[0]]=(torch.sum((self.envelope_w[one_d_index]*one_electron[:,j,:])+self.envelope_g[one_d_index],dim=1))*torch.sum(
                        torch.exp(-torch.abs(torch.norm(self.sigma[one_d_index]*one_electron_vector_permuted[:,j,:,:],dim=2
                                                               )))*self.pi[one_d_index].T,dim=1)
            #print(torch.det(psi_up[:,k,:,:])[0])
            #print(torch.det(psi_down[:,k,:,:])[0])
            d_down = torch.det(psi_down[:,k,:,:].clone())
            d_up = torch.det(psi_up[:,k,:,:].clone())
            d= d_up * d_down
            psi = psi + d
        return psi




class FerminetModel(TorchModel):
    """A deep-learning based Variational Monte Carlo method [1]_ for calculating the ab-initio
    solution of a many-electron system.

    This model aims to calculate the ground state energy of a multi-electron system
    using a baseline solution as the Hartree-Fock. An MCMC technique is used to sample
    electrons and DNNs are used to caluclate the square magnitude of the wavefunction,
    in which electron-electron repulsions also are included in the calculation(in the
    form of Jastrow factor envelopes). The model requires only the nucleus' coordinates
    as input.

    This method is based on the following paper:

    References
    ----------
    .. [1] Spencer, James S., et al. Better, Faster Fermionic Neural Networks. arXiv:2011.07125, arXiv, 13 Nov. 2020. arXiv.org, http://arxiv.org/abs/2011.07125.

    Note
    ----
    This class requires pySCF to be installed.
    """

    def __init__(
        self,
        nucleon_coordinates: List[List],
        spin: int,
        ion_charge: int,
        seed: Optional[int] = None,
        batch_no: int = 10,
        pretrain=True,
    ):
        """
    Parameters:
    -----------
    nucleon_coordinates: List[List]
      A list containing nucleon coordinates as the values with the keys as the element's symbol.
    spin: int
      The total spin of the molecule system.
    ion_charge: int
      The total charge of the molecule system.
    seed_no: int, optional (default None)
      Random seed to use for electron initialization.
    batch_no: int, optional (default 10)
      Number of batches of the electron's positions to be initialized.

    Attributes:
    -----------
    nucleon_pos: np.ndarray
        numpy array value of nucleon_coordinates
    electron_no: np.ndarray
        Torch tensor containing electrons for each atom in the nucleus
    molecule: ElectronSampler
        ElectronSampler object which performs MCMC and samples electrons
    """
        self.nucleon_coordinates = nucleon_coordinates
        self.seed = seed
        self.batch_no = batch_no
        self.spin = spin
        self.ion_charge = ion_charge
        self.batch_no = batch_no

        no_electrons = []
        nucleons = []
        electronegativity = []

        table = Chem.GetPeriodicTable()
        index = 0
        for i in self.nucleon_coordinates:
            atomic_num = table.GetAtomicNumber(i[0])
            electronegativity.append([index, ALLEN_ELECTRONEGATIVTY[i[0]]])
            no_electrons.append([atomic_num])
            nucleons.append(i[1])
            index += 1

        self.electron_no: np.ndarray = np.array(no_electrons)
        charge: np.ndarray = self.electron_no.reshape(
            np.shape(self.electron_no)[0])
        self.nucleon_pos: np.ndarray = np.array(nucleons)
        electro_neg = np.array(electronegativity)

        # Initialization for ionic molecules
        if np.sum(self.electron_no) < self.ion_charge:
            raise ValueError("Given charge is not initializable")

        # Initialization for ionic molecules
        if self.ion_charge != 0:
            if len(nucleons
                  ) == 1:  # for an atom, directly the charge is applied
                self.electron_no[0][0] -= self.ion_charge
            else:  # for a multiatomic molecule, the most electronegative atom gets a charge of -1 and vice versa. The remaining charges are assigned in terms of decreasing(for anionic charge) and increasing(for cationic charge) electronegativity.
                electro_neg = electro_neg[electro_neg[:, 1].argsort()]
                if self.ion_charge > 0:
                    for iter in range(self.ion_charge):
                        self.electron_no[int(electro_neg[iter][0])][0] -= 1
                else:
                    for iter in range(-self.ion_charge):
                        self.electron_no[int(electro_neg[-1 - iter][0])][0] += 1

        total_electrons = np.sum(self.electron_no)

        if self.spin >= 0:
            self.up_spin = (total_electrons + 2 * self.spin) // 2
            self.down_spin = total_electrons - self.up_spin
        else:
            self.down_spin = (total_electrons - 2 * self.spin) // 2
            self.up_spin = total_electrons - self.down_spin

        if self.up_spin - self.down_spin != self.spin:
            raise ValueError("Given spin is not feasible")

        nucl = torch.from_numpy(self.nucleon_pos)
        self.model = Ferminet(nucl,
                         spin=(self.up_spin, self.down_spin),
                         nuclear_charge=torch.tensor(charge),
                         batch_size=self.batch_no)

        self.molecule: ElectronSampler = ElectronSampler(
            batch_no=self.batch_no,
            central_value=self.nucleon_pos,
            seed=self.seed,
            f=lambda x: test_f(x),  # Will be replaced in successive PR
            steps=1000,
            steps_per_update=20
        )  # sample the electrons using the electron sampler
        self.molecule.gauss_initialize_position(
            self.electron_no)  # initialize the position of the electrons
        adam = optimizers.AdamW()
        super(FerminetModel, self).__init__(
            self.model, optimizer=adam,
            loss=L2Loss())  # will update the loss in successive PR

    def prepare_hf_solution(self, x: np.ndarray) -> np.ndarray:
        """Prepares the HF solution for the molecule system which is to be used in pretraining

        Parameters
        ----------
        x: np.ndarray
        Numpy array of shape (number of electrons,3), which indicates the sampled electron's positions

        Returns
        -------
        hf_value: np.ndarray
        Numpy array of shape (number of electrons, number of electrons ) where ith row & jth value corresponds to the ith hartree fock orbital at the jth electron's coordinate
    """
        try:
            import pyscf
        except ModuleNotFoundError:
            raise ImportError("This module requires pySCF")

        molecule = ""
        for i in range(len(self.nucleon_pos)):
            molecule = molecule + self.nucleon_coordinates[i][0] + " " + str(
                self.nucleon_coordinates[i][1][0]) + " " + str(
                    self.nucleon_coordinates[i][1][1]) + " " + str(
                        self.nucleon_coordinates[i][1][2]) + ";"
        mol = pyscf.gto.Mole(atom=molecule, basis='sto-3g')
        mol.parse_arg = False
        mol.unit = 'Bohr'
        mol.spin = (self.up_spin - self.down_spin)
        mol.charge = self.ion_charge
        mol.build(parse_arg=False)
        mf = pyscf.scf.RHF(mol)
        mf.kernel()

        coefficients_all = mf.mo_coeff[:, :mol.nelectron]
        # Get the positions of all the electrons
        electron_positions = mol.atom_coords()[:mol.nelectron]
        # Evaluate all molecular orbitals at the positions of all the electrons
        orbital_values = np.dot(mol.eval_gto("GTOval", electron_positions),
                                coefficients_all)
        return orbital_values
