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
                 batch_size: int = 8) -> None:
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

        self.nucleon_pos = nucleon_pos.to("cpu")
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

        self.running_diff = torch.zeros(self.batch_size).to("cpu")

        self.v.append(
            nn.Linear(8 + 3 * 4 * self.nucleon_pos.size()[0],
                      n_one[0],
                      bias=True))
        self.w.append(nn.Linear(4, n_two[0], bias=True))
        for i in range(1, self.layers):
            self.v.append(
                nn.Linear(3 * n_one[i - 1] + 2 * n_two[i - 1],
                          n_one[i],
                          bias=True))
            self.w.append(nn.Linear(n_two[i - 1], n_two[i], bias=True))

        for i in range(self.determinant):
            for j in range(self.total_electron):
                self.envelope_w.append(
                    torch.nn.init.kaiming_uniform(torch.empty(n_one[-1],
                                                              1)).squeeze(-1))
                self.envelope_g.append(
                    torch.nn.init.uniform(torch.empty(1)).squeeze(0))
                for k in range(self.nucleon_pos.size()[0]):
                    self.sigma.append(
                        torch.nn.init.uniform(
                            torch.empty(self.nucleon_pos.size()[0],
                                        1)).squeeze(0))
                    self.pi.append(
                        torch.nn.init.uniform(
                            torch.empty(self.nucleon_pos.size()[0],
                                        1)).squeeze(0))

    def forward(self, input):
        # creating one and two electron features
        self.input = torch.from_numpy(input).to("cpu")
        self.input.requires_grad = True
        self.input = self.input.reshape((self.batch_size, -1, 3))
        two_electron_vector = self.input.unsqueeze(1) - self.input.unsqueeze(2)
        two_electron_distance = torch.norm(two_electron_vector,
                                           dim=3).unsqueeze(3)
        two_electron = torch.cat((two_electron_vector, two_electron_distance),
                                 dim=3)
        two_electron = torch.reshape(
            two_electron,
            (self.batch_size, self.total_electron, self.total_electron, -1))

        one_electron_vector = self.input.unsqueeze(
            1) - self.nucleon_pos.unsqueeze(1)
        one_electron_distance = torch.norm(one_electron_vector, dim=3)
        one_electron = torch.cat(
            (one_electron_vector, one_electron_distance.unsqueeze(-1)), dim=3)
        one_electron = torch.reshape(one_electron.permute(0, 2, 1, 3),
                                     (self.batch_size, self.total_electron, -1))
        one_electron_vector_permuted = one_electron_vector.permute(0, 2, 1, 3)

        for l in range(len(self.n_one)):
            g_one_up = torch.mean(one_electron[:, :self.spin[0], :], dim=-2)
            g_one_down = torch.mean(one_electron[:, self.spin[0]:, :], dim=-2)
            one_electron_tmp = torch.zeros(self.batch_size, self.total_electron,
                                           self.n_one[l])
            two_electron_tmp = torch.zeros(self.batch_size, self.total_electron,
                                           self.total_electron, self.n_two[l])
            for i in range(self.total_electron):
                g_two_up = torch.mean(two_electron[:, i, :self.spin[0], :],
                                      dim=1)
                g_two_down = torch.mean(two_electron[:, i, self.spin[0]:, :],
                                        dim=1)
                f = torch.cat((one_electron[:, i, :], g_one_up, g_one_down,
                               g_two_up, g_two_down),
                              dim=1)
                if l == 0 or (self.n_one[l]
                              != self.n_one[l - 1]) or (self.n_two[l]
                                                        != self.n_two[l - 1]):
                    one_electron_tmp[:, i, :] = torch.tanh(self.v[l](f.to(
                        torch.float32).to("cpu")))
                    two_electron_tmp[:, i, :, :] = torch.tanh(self.w[l](
                        two_electron[:, i, :, :].to(torch.float32).to("cpu")))
                else:
                    one_electron_tmp[:, i, :] = torch.tanh(self.v[l](f.to(
                        torch.float32).to("cpu"))) + one_electron[:, i, :].to(
                            torch.float32).to("cpu")
                    two_electron_tmp[:, i, :, :] = torch.tanh(self.w[l](
                        two_electron[:, i, :, :].to(torch.float32).to("cpu")
                    )) + two_electron[:, i, :].to(torch.float32).to("cpu")
            one_electron = one_electron_tmp.to("cpu")
            two_electron = two_electron_tmp.to("cpu")

        psi = torch.zeros(self.batch_size).to("cpu")
        self.psi_up = torch.zeros(self.batch_size, self.determinant,
                                  self.spin[0], self.spin[0]).to("cpu")
        self.psi_down = torch.zeros(self.batch_size, self.determinant,
                                    self.spin[1], self.spin[1]).to("cpu")
        #psi_up.requires_grad = True
        #psi_down.requires_grad =  True
        for k in range(self.determinant):
            for i in range(self.spin[0]):
                one_d_index = (k * (self.total_electron)) + i
                for j in range(self.spin[0]):
                    self.psi_up[:, k, i, j] = (torch.sum(
                        (self.envelope_w[one_d_index] * one_electron[:, j, :]) +
                        self.envelope_g[one_d_index],
                        dim=1)) * torch.sum(torch.exp(-torch.abs(
                            torch.norm(self.sigma[one_d_index] *
                                       one_electron_vector_permuted[:, j, :, :],
                                       dim=2))) * self.pi[one_d_index].T,
                                            dim=1)

            for i in range(self.spin[0], self.spin[0] + self.spin[1]):
                one_d_index = (k * (self.total_electron)) + i
                for j in range(self.spin[0], self.spin[0] + self.spin[1]):
                    self.psi_down[:, k, i - self.spin[0], j - self.spin[0]] = (
                        torch.sum((self.envelope_w[one_d_index] *
                                   one_electron[:, j, :]) +
                                  self.envelope_g[one_d_index],
                                  dim=1)
                    ) * torch.sum(torch.exp(-torch.abs(
                        torch.norm(self.sigma[one_d_index] *
                                   one_electron_vector_permuted[:, j, :, :],
                                   dim=2))) * self.pi[one_d_index].T,
                                  dim=1)
            #print(torch.det(psi_up[:,k,:,:])[0])
            #print(torch.det(psi_down[:,k,:,:])[0])
            d_down = torch.det(self.psi_down[:, k, :, :].clone())
            d_up = torch.det(self.psi_up[:, k, :, :].clone())
            d = d_up * d_down
            psi = psi + d
        return psi

    def loss(self, psi_up_mo, psi_down_mo, pretrain=True):
        if pretrain == True:
            psi_up_mo = torch.from_numpy(psi_up_mo).unsqueeze(1).to("cpu")
            psi_down_mo = torch.from_numpy(psi_down_mo).unsqueeze(1).to("cpu")
            self.running_diff = self.running_diff + (
                self.psi_up - psi_up_mo)**2 + (self.psi_down - psi_down_mo)**2


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
        batch_no: int = 4,
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
            f=lambda x: self.f(x),  # Will be replaced in successive PR
            steps=10,
            steps_per_update=10
        )  # sample the electrons using the electron sampler
        self.molecule.gauss_initialize_position(
            self.electron_no)  # initialize the position of the electrons
        self.prepare_hf_solution()
        adam = optimizers.AdamW()
        super(FerminetModel, self).__init__(
            self.model,
            loss=self.model.loss)  # will update the loss in successive PR

    def f(self, x) -> np.ndarray:
        # dummy function which can be passed as the parameter f. f gives the log probability
        # TODO replace this function with forward pass of the model in future
        output = self.model.forward(x)
        np_output = output.detach().cpu().numpy()
        up_spin_mo, down_spin_mo = self.evaluate_hf(x)
        hf_product = np.product(
            np.diagonal(up_spin_mo, axis1=1, axis2=2)**2, axis=1) * np.product(
                np.diagonal(down_spin_mo, axis1=1, axis2=2)**2, axis=1)
        self.loss(up_spin_mo, down_spin_mo, pretrain=True)
        return np.log(hf_product + np_output**2) + np.log(0.5)

    def prepare_hf_solution(self) -> np.ndarray:
        """Prepares the HF solution for the molecule system which is to be used in pretraining

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
        self.mol = pyscf.gto.Mole(atom=molecule, basis='sto-3g')
        self.mol.parse_arg = False
        self.mol.unit = 'Bohr'
        self.mol.spin = (self.up_spin - self.down_spin)
        self.mol.charge = self.ion_charge
        self.mol.build(parse_arg=False)
        self.mf = pyscf.scf.UHF(self.mol)
        _ = self.mf.kernel()

    def evaluate_hf(self, x):
        x = np.reshape(x, [-1, 3 * (self.up_spin + self.down_spin)])
        leading_dims = x.shape[:-1]
        x = np.reshape(x, [-1, 3])
        coeffs = self.mf.mo_coeff
        gto_op = 'GTOval_sph'
        ao_values = self.mol.eval_gto(gto_op, x)
        mo_values = tuple(np.matmul(ao_values, coeff) for coeff in coeffs)
        mo_values = [
            np.reshape(mo, leading_dims + (self.up_spin + self.down_spin, -1))
            for mo in mo_values
        ]
        #mo_values *= 2
        return mo_values[0][..., :self.up_spin, :self.up_spin], mo_values[1][
            ..., self.up_spin:, :self.down_spin]

    def fit(self, nb_epoch: int = 200, nb_pretrain_epoch: int = 100):
        # burn - in
        # pretraining
        optimizer = torch.optim.Adam(self.model.parameters(),
                                     lr=0.05,
                                     weight_decay=1.0)
        for i in range(nb_pretrain_epoch):
            optimizer.zero_grad()
            self.molecule.move()
            self.model.running_diff = torch.mean(self.model.running_diff /
                                                 self.molecule.steps)
            self.model.running_diff.backward()
            optimizer.step()
            print("loss->>>>")
            print(self.model.running_diff)
            self.model.running_diff = torch.zeros(self.batch_no).to("cpu")
