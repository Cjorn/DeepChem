from deepchem.data.data_loader import DFTYamlLoader
from deepchem.models.dft.scf import XCNNSCF
import torch
from deepchem.feat.dft_data import DFTEntry, DFTSystem
from deepchem.models.dft.nnxc import HybridXC
from deepchem.models.losses import Loss, L2Loss
from deepchem.models.torch_models.torch_model import TorchModel
from typing import List, Optional, Tuple, Any
import numpy as np


class DFTXC(torch.nn.Module):
    """
    """
    def __init__(self,
                 xcstr: str,
                 ninp: int = 2,
                 nhid: int = 10,
                 ndepths: int = 1,
                 modeltype: int = 1):
        """
        Parameters
        ----------
        xcstr: str
            The choice of xc to use. Some of the commonly used ones are:
            lda_x, lda_c_pw, lda_c_ow, lda_c_pz, lda_xc_lp_a, lda_xc_lp_b.
            The rest of the possible values can be found under the
            "LDA Functionals" section in the reference given below.
        """
        super(DFTXC, self).__init__()
        self.model = construct_nn_model(ninp, nhid, ndepths,
                                        modeltype).to(torch.double)

    def forward(self, inputs):
        """
        Parameters
        ----------
        inputs: list of tensors containing dataset 
        
        Returns
        -------
        torch.Tensor
            Calculated value of the data point after running the Kohn Sham iterations
            using the neural network XC functional"
        """ 
        hybridxc = HybridXC("lda_x", self.model, aweight0=0.0)
        for entry in inputs:
            evl = XCNNSCF(hybridxc, entry)
            qcs = []
            for system in entry.get_systems():
                qcs.append(evl.run(system))
            if entry.entry_type == 'dm':
                return torch.as_tensor(entry.get_val(qcs)[0])
            else:
                return torch.as_tensor(entry.get_val(qcs))


class XCModel(TorchModel):

    def __init__(self,
                 xc_type: str,
                 ninp: int = 2,
                 nhid: int = 10,
                 ndepths: int = 1,
                 modeltype: int = 1,
                 n_tasks: int = 0,
                 log_frequency: int = 0,
                 mode: str = 'classification',
                 device: Optional[torch.device] = None,
                 **kwargs) -> None:
        model = DFTXC(xc_type, ninp, nhid, ndepths, modeltype)
        self.xc = xc_type
        self.model = model
        loss: Loss = L2Loss()
        output_types = ['loss', 'predict']
        self.mode = mode
        super(XCModel, self).__init__(model,
                                      loss=loss,
                                      output_types=output_types,
                                      **kwargs)

    def _prepare_batch(self, batch):

        inputs, labels, weights = batch
        labels = [torch.from_numpy(inputs[0][0].get_true_val())]
        labels[0].requires_grad_()
        w = np.array([1.0])
        weights = [torch.from_numpy(w)]
        return (inputs, labels, weights)


class ExpM1Activation(torch.nn.Module):

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.exp(x) - 1


def construct_nn_model(ninp: int, nhid: int, ndepths: int, modeltype: int):
    if modeltype == 1:
        layers = []
        for i in range(ndepths):
            n1 = ninp if i == 0 else nhid
            layers.append(torch.nn.Linear(n1, nhid))
            layers.append(torch.nn.Softplus())
        layers.append(torch.nn.Linear(nhid, 1, bias=False))
        return torch.nn.Sequential(*layers)
    elif modeltype == 2:
        layers = []
        for i in range(ndepths):
            n1 = ninp if i == 0 else nhid
            layers.append(torch.nn.Linear(n1, nhid))
            if i < ndepths - 1:
                layers.append(torch.nn.Softplus())
            else:
                layers.append(ExpM1Activation())
        layers.append(torch.nn.Linear(nhid, 1, bias=False))
        return torch.nn.Sequential(*layers)
