"""
Implementation of KFAC with mean centered output and graidents, a second order optimizer, in PyTorch.
"""
import math
from typing import Optional, Callable, Dict, Tuple, List, Union
try:
    import torch
    import torch.optim as optim
    has_pytorch = True

except ModuleNotFoundError:
    has_pytorch = False


class KFACOptimizer(optim.Optimizer):
    """"
    This class implement the second order optimizer - KFAC, which uses Kronecker factor products of inputs and the gradients to
    get the approximate inverse fisher matrix, which is used to update the model parameters. Presently this optimizer works only
    on liner and 2D convolution layers. If you want to know more details about KFAC, please check the paper [1]_ and [2]_.

    References:
    -----------
    [1] Martens, James, and Roger Grosse. Optimizing Neural Networks with Kronecker-Factored Approximate Curvature.
    arXiv:1503.05671, arXiv, 7 June 2020. arXiv.org, http://arxiv.org/abs/1503.05671.
    [2] Grosse, Roger, and James Martens. A Kronecker-Factored Approximate Fisher Matrix for Convolution Layers.
    arXiv:1602.01407, arXiv, 23 May 2016. arXiv.org, http://arxiv.org/abs/1602.01407.
    """

    def __init__(
        self,
        model: torch.nn.Module,
        lr: float = 0.001,
        momentum: float = 0.9,
        stat_decay: float = 0.95,
        damping: float = 0.001,
        kl_clip: float = 0.001,
        weight_decay: float = 0,
        TCov: int = 10,
        TInv: int = 10,
        batch_averaged: bool = True,
        mean: bool = False,
    ):
        """
        Parameters:
        -----------
        model: torch.nn.Module
          The model to be optimized.
        lr: float (default: 0.001)
          Learning rate for the optimizer.
        momentum: float (default: 0.9)
          Momentum for the optimizer.
        stat_decay: float (default: 0.95)
          Decay rate for the update of covariance matrix with mean.
        damping: float (default: 0.001)
          damping factor for the update of covariance matrix.
        kl_clip: float (default: 0.001)
          Clipping value for the update of covariance matrix.
        weight_decay: float (default: 0)
          weight decay for the optimizer.
        Tcov: int (default: 10)
          The number of steps to update the covariance matrix.
        Tinv: int (default: 100)
          The number of steps to calculate the inverse of covariance matrix.
        batch_averaged: bool (default: True)
          States whether to use batch averaged covariance matrix.
        mean: bool (default: False)
          States whether to use mean centered covariance matrix.
        """

        if lr < 0.0:
            raise ValueError("Invalid learning rate: {}".format(lr))
        if momentum < 0.0:
            raise ValueError("Invalid momentum value: {}".format(momentum))
        if weight_decay < 0.0:
            raise ValueError(
                "Invalid weight_decay value: {}".format(weight_decay))
        defaults = dict(lr=lr,
                        momentum=momentum,
                        damping=damping,
                        weight_decay=weight_decay)
        super(KFACOptimizer, self).__init__(model.parameters(), defaults)
        self.batch_averaged = batch_averaged

        self.known_modules = {'Linear', 'Conv2d'}

        self.modules: List[torch.nn.Module] = []

        self.model = model

        self.total_steps = total_steps
        self.mean = mean

        self.steps = 0
        self.input_number_forward = 0
        self.input_number_backward = 0
        self.expected_grad: Dict[torch.nn.Module, torch.Tensor] = {}
        self.expected_input: Dict[torch.nn.Module, torch.Tensor] = {}

        self.local_count_forward = 0
        self.local_count_backward = 0

        self.list_aa: Dict[torch.nn.Module, torch.Tensor] = {}
        self.list_gg: Dict[torch.nn.Module, torch.Tensor] = {}
        self.Q_a: Dict[torch.nn.Module, torch.Tensor] = {}
        self.Q_g: Dict[torch.nn.Module, torch.Tensor] = {}
        self.d_a: Dict[torch.nn.Module, torch.Tensor] = {}
        self.d_g: Dict[torch.nn.Module, torch.Tensor] = {}
        self.stat_decay = stat_decay

        self.kl_clip = kl_clip
        self.TCov = TCov
        self.TInv = TInv

        self._prepare_model()

    @torch.no_grad()
    def try_contiguous(self, x: torch.Tensor) -> torch.Tensor:
        """
        Checks the memory layout of the input tensor and changes it to contiguous type.

        Parameters:
        -----------
        x: torch.Tensor
          The input tensor to be made contiguous in memory, if it is not so.

        Return:
        -------
        torch.Tensor
          Tensor with contiguous memory
        """
        if not x.is_contiguous():
            x = x.contiguous()

        return x

    @torch.no_grad()
    def _extract_patches(
            self, x: torch.Tensor, kernel_size: Tuple[int,
                                                      ...], stride: Tuple[int,
                                                                          ...],
            padding: Union[int, str, Tuple[int, ...]]) -> torch.Tensor:
        """
        Extract patches of a given size from the input tensor given. Used in calculating
        the matrices for the kronecker product in the case of 2d Convolutions.

        Parameters:
        -----------
        x: torch.Tensor
          The input feature maps. with the size of (batch_size, in_c, h, w)
        kernel_size: Tuple[int, ...]
          the kernel size of the conv filter.
        stride: Tuple[int, ...]
          the stride of conv operation.
        padding: Union[int, str, Tuple[int, ...]]
          number of paddings. be a tuple of two elements

        Return:
        -------
        torch.Tensor:
          Extracted patches with shape (batch_size, out_h, out_w, in_c*kh*kw)
        """
        if isinstance(padding, tuple):
            if padding[0] + padding[1] > 0:
                x = torch.nn.functional.pad(
                    x, (padding[1], padding[1], padding[0],
                        padding[0])).data  # Actually check dims
        elif isinstance(padding, int):
            if padding > 0:
                x = torch.nn.functional.pad(
                    x, (padding, padding, padding, padding)).data
        elif isinstance(padding, str):
            if padding == 'VALID':
                pad = int((kernel_size[0] - 1) / 2)
                x = torch.nn.functional.pad(x, (pad, pad, pad, pad)).data

        x = x.unfold(2, kernel_size[0], stride[0])
        x = x.unfold(3, kernel_size[1], stride[1])
        x = x.transpose_(1, 2).transpose_(2, 3).contiguous()
        x = x.view(x.size(0), x.size(1), x.size(2),
                   x.size(3) * x.size(4) * x.size(5))
        return x

    @torch.no_grad()
    def compute_cov_a(self, a: torch.Tensor,
                      layer: torch.nn.Module) -> torch.Tensor:
        """
        Compute the covariance matrix of the A matrix (the output of each layer).

        Parameters:
        -----------
        a: torch.Tensor
          It is the output of the layer for which the covariance matrix should be calculated.
        layer: torch.nn.Module
          It specifies the type of layer from which the output of the layer is taken.

        Returns:
        --------
        torch.Tensor
          The covariance matrix of the A matrix.
        """
        if isinstance(layer, torch.nn.Linear):
            batch_size = a.size(0)
            try:
                dim = a.size(1)
            except IndexError:
                a = a.unsqueeze(0)
            if layer.bias is not None:
                a = torch.cat((a, a.new(a.size(0), 1).fill_(1)), 1)

        elif isinstance(layer, torch.nn.Conv2d):
            batch_size = a.size(0)
            a = self._extract_patches(a, layer.kernel_size, layer.stride,
                                      layer.padding)
            spatial_size = a.size(1) * a.size(2)
            a = a.view(-1, a.size(-1))
            if layer.bias is not None:
                a = torch.cat((a, a.new(a.size(0), a.size(1)).fill_(1)), 1)
            a = a / spatial_size

        return a.t() @ (a / batch_size)

    @torch.no_grad()
    def compute_cov_g(self, g: torch.Tensor,
                      layer: torch.nn.Module) -> torch.Tensor:
        """
        Compute the covariance matrix of the G matrix (the gradient of the layer).

        Parameters:
        -----------
        g: torch.Tensor
          It is the gradient of the layer for which the covariance matrix should be calculated.
        layer: torch.nn.Module
          It specifies the type of layer from which the output of the layer is taken.

        Returns:
        --------
        torch.Tensor
          The covariance matrix of the G matrix.
        """
        if isinstance(layer, torch.nn.Linear):
            try:
                dim = g.size(1)
            except IndexError:
                g = g.unsqueeze(0)

            batch_size = g.size(0)

            if self.batch_averaged:
                cov_g = g.t() @ (g * batch_size)
            else:
                cov_g = g.t() @ (g / batch_size)

        elif isinstance(layer, torch.nn.Conv2d):
            spatial_size = g.size(2) * g.size(3)
            batch_size = g.shape[0]
            g = g.transpose(1, 2).transpose(2, 3)
            g = self.try_contiguous(g)
            g = g.view(-1, g.size(-1))
            if self.batch_averaged:
                g = g * batch_size
            g = g * spatial_size
            cov_g = g.t() @ (g / g.size(0))

        return cov_g

    @torch.no_grad()
    def _save_input(self, module: torch.nn.Module, input: torch.Tensor):
        """
        Updates the input of the layer using exponentially weighted averages of the layer input.

        Parameters:
        -----------
        module: torch.nn.Module
          specifies the layer for which the input should be taken
        input: torch.Tensor
           the input matrix which should get updated
        """
        self.expected_input = {}
        if self.steps % self.TCov == 0:
            aa = self.compute_cov_a(input[0].data, module)
            aa = torch.unsqueeze(aa, 0)
            # Initialize buffers
            if self.input_number_forward == 0:
                self.expected_input[module] = torch.diag(
                    aa.new(aa.size(0)).fill_(1))
                self.list_aa[module] = torch.diag(aa.new(aa.size(0)).fill_(1))
            try:
                self.expected_input[module] = self.stat_decay * (
                    self.expected_input[module]) + aa * (1 - self.stat_decay)
                self.list_aa[
                    module] = self.stat_decay * self.list_aa[module] + (
                        aa - self.list_aa[module]) * (1 - self.stat_decay)
            except KeyError:
                self.expected_input[module] = torch.diag(
                    aa.new(aa.size(0)).fill_(1))
                self.list_aa[module] = torch.diag(aa.new(aa.size(0)).fill_(1))
                self.expected_input[module] = self.stat_decay * (
                    self.expected_input[module]) + aa * (1 - self.stat_decay)
                self.list_aa[
                    module] = self.stat_decay * self.list_aa[module] + (
                        aa - self.list_aa[module]) * (1 - self.stat_decay)
            self.input_number_forward += 1

    @torch.no_grad()
    def _save_grad_output(self, module: torch.nn.Module,
                          grad_input: torch.Tensor, grad_output: torch.Tensor):
        """
        Updates the backward gradient of the layer using exponentially weighted averages of the layer input.

        Parameters:
        -----------
        module: torch.nn.Module
          specifies the layer for which the gradient should be taken
        input: torch.Tensor
          the gradient matrix which should get updated
        """
        # Accumulate statistics for Fisher matrices
        if self.steps % self.TCov == 0:
            gg = self.compute_cov_g(grad_output[0].data, module)
            try:
                dim = gg.size(1)
            except IndexError:
                gg = gg.unsqueeze(0)
            # Initialize buffers
            if self.input_number_backward == 0:
                self.expected_grad[module] = torch.diag(
                    gg.new(gg.size(0)).fill_(1))
                self.list_gg[module] = torch.diag(gg.new(gg.size(0)).fill_(1))
            try:
                self.expected_grad[module] = self.stat_decay * (
                    self.expected_grad[module]) + gg * (1 - self.stat_decay)
                self.list_gg[module] = self.stat_decay * self.list_gg[module] + (
                    gg - self.expected_input[module]) * (1 - self.stat_decay)
            except KeyError:
                self.expected_grad[module] = torch.diag(
                    gg.new(gg.size(0)).fill_(1))
                self.list_gg[module] = torch.diag(gg.new(gg.size(0)).fill_(1))
                self.expected_grad[module] = self.stat_decay * (
                    self.expected_grad[module]) + gg * (1 - self.stat_decay)
                self.list_gg[module] = self.stat_decay * self.list_gg[module] + (
                    gg - self.expected_input[module]) * (1 - self.stat_decay)
        self.input_number_backward

    @torch.no_grad()
    def _prepare_model(self):
        """"
        Attaches hooks(saving the ouptut and grad according to the update function) to the model for
        to calculate gradients at every step.
        """
        self.count = 0
        for module in self.model.modules():
            classname = module.__class__.__name__
            if classname in self.known_modules:
                self.modules.append(module)
                module.register_backward_hook(self._save_grad_output)
                module.register_forward_pre_hook(self._save_input)
                self.count += 1

    @torch.no_grad()
    def _update_inv(self, m: torch.nn.Module):
        """
        Does eigen decomposition of the input(A) and gradient(G) matrix for computing inverse of the ~ fisher.

        Parameter:
        ----------
        m: torch.nn.Module
          This is the layer for which the eigen decomposition should be done on.
        """
        eps = 1e-10  # for numerical stability
        self.d_a[m], self.Q_a[m] = torch.symeig(self.list_aa[m],
                                                eigenvectors=True)
        self.d_g[m], self.Q_g[m] = torch.symeig(self.list_gg[m],
                                                eigenvectors=True)

        self.d_a[m].mul_((self.d_a[m] > eps).float())
        self.d_g[m].mul_((self.d_g[m] > eps).float())

    @torch.no_grad()
    def get_matrix_form_grad(self, m: torch.nn.Module):
        """
        Returns the gradient of the layer in a matrix form

        Parameter:
        ----------
        m: torch.nn.Module
          the layer for which the gradient must be calculated

        Return:
        -------
        torch.tensor
          a matrix form of the gradient. it should be a [output_dim, input_dim] matrix.
        """
        if isinstance(m, torch.nn.Conv2d):
            p_grad_mat = m.weight.grad.data.view(
                m.weight.grad.data.size(0), -1)  # n_filters * (in_c * kw * kh)
        elif isinstance(m, torch.nn.Linear):
            p_grad_mat = m.weight.grad.data
            try:
                size = p_grad_mat.size()[1]
            except IndexError:
                p_grad_mat = p_grad_mat.unsqueeze(1)

        else:
            raise NotImplementedError(
                "KFAC optimizer currently support only Linear and Conv2d layers"
            )

        if m.bias is not None:
            if isinstance(m.bias.grad.data, torch.Tensor):
                try:
                    size = m.bias.grad.data.size()[0]
                    p_grad_mat = torch.cat(
                        (p_grad_mat, m.bias.grad.data.view(-1, 1)), 1)
                except RuntimeError:
                    p_grad_mat = torch.cat(
                        (p_grad_mat, m.bias.grad.data.view(-1, 1)), 0)
                except IndexError:
                    m.bias.grad.data = m.bias.grad.data.unsqueeze(0)
                    p_grad_mat = torch.cat(
                        (p_grad_mat, m.bias.grad.data.view(-1, 1)), 0)
                    p_grad_mat = p_grad_mat.reshape(p_grad_mat.size()[1],
                                                    p_grad_mat.size()[0])
            else:
                raise TypeError("bias.grad.data should be a Tensor")
        return p_grad_mat

    @torch.no_grad()
    def _get_natural_grad(self, m: torch.nn.Module, p_grad_mat: torch.Tensor,
                          damping: float) -> List[torch.Tensor]:
        """
        This function returns the product of inverse of the fisher matrix and the weights gradient.

        Parameters:
        -----------
        m: torch.nn.Module
          Specifies the layer for which the calculation must be done on.
        p_grad_mat: torch.Tensor
          the gradients in matrix form isinstance(m.weight.grad.data, torch.Tensor) and i
        damping: float
          the damping factor for the calculation

        Return:
        -------
        torch.Tensor
          the product of inverse of the fisher matrix and the weights gradient.
        """
        # p_grad_mat is of output_dim * input_dim
        # inv((ss')) p_grad_mat inv(aa') = [ Q_g (1/R_g) Q_g^T ] @ p_grad_mat @ [Q_a (1/R_a) Q_a^T]
        try:
            v1 = self.Q_g[m].t() @ p_grad_mat @ self.Q_a[m]
        except RuntimeError:
            p_grad_mat = p_grad_mat.reshape(p_grad_mat.size()[1],
                                            p_grad_mat.size()[0])
            v1 = self.Q_g[m].t() @ p_grad_mat @ self.Q_a[m]
        v2 = v1 / (self.d_g[m].unsqueeze(1) * self.d_a[m].unsqueeze(0) +
                   damping)
        try:
            a = self.Q_g[m] @ v2 @ self.Q_a[m].t()
        except RuntimeError:
            a = self.Q_g[m][0] @ v2 @ self.Q_a[m][0].t()
        if m.bias is not None:
            # we always put gradient w.r.t weight in [0]
            # and w.r.t bias in [1]
            v = [a[:, :-1], a[:, -1:]]
            try:
                v[0] = v[0].view(m.weight.grad.data.size())
            except RuntimeError:
                v[0] = v[0].view(m.weight.grad.data.size(1))
            try:
                v[1] = v[1].view(m.bias.grad.data.size())
            except RuntimeError:
                pass
        else:
            try:
                v = [a.view(m.weight.grad.data.size())]
            except RuntimeError:
                v = [a.view(m.weight.grad.data.size(1))]
        return v

    @torch.no_grad()
    def _kl_clip_and_update_grad(self, updates: Dict[torch.nn.Module,
                                                     List[torch.Tensor]],
                                 lr: float):
        """
        Performs clipping on the updates matrix, if the value is large. Then final value is updated in the backwards gradient data

        Parameters:
        -----------
        updates: Dict[torch.nn.Module,List[torch.Tensor]]
          A dicitonary containing the product of gradient and fisher inverse of each layer.
        lr: float
          learning rate of the optimizer
        """
        # do kl clip
        vg_sum = 0.0
        for m in self.modules:
            v = updates[m]
            vg_sum += (v[0] * m.weight.grad.data * lr**2).sum().item()
            if m.bias is not None:
                vg_sum += (v[1] * m.bias.grad.data * lr**2).sum().item()
        nu = min(1.0, math.sqrt(self.kl_clip / vg_sum))

        for m in self.modules:
            v = updates[m]
            if isinstance(m.weight.grad.data, torch.Tensor):
                m.weight.grad.data.copy_(v[0])
                m.weight.grad.data.mul_(nu)
            else:
                raise TypeError("weight.grad.data should be a Tensor")
            if m.bias is not None:
                if isinstance(m.bias.grad.data, torch.Tensor):
                    try:
                        m.bias.grad.data.copy_(v[1])
                    except RuntimeError:
                        m.bias.grad.data.copy_(v[1].squeeze(0))
                    m.bias.grad.data.mul_(nu)
                else:
                    raise TypeError("bias.grad.data should be a Tensor")

    @torch.no_grad()
    def _step(self, closure: Optional[Callable] = None):
        """
        Called in every step of the optimizer, updating the model parameters from the gradient by the KFAC equation.
        Also, performs weight decay and adds momentum if any.

        Parameters:
        -----------
        closure: Callable, optional(default: None)
         an optional customizable function to be passed which can be used to clear the gradients and other compute loss for every step.
        """
        for group in self.param_groups:
            weight_decay = group['weight_decay']
            momentum = group['momentum']
            lr = group['lr']

            for p in group['params']:
                if p.grad is None:
                    continue
                d_p = p.grad.data
                if weight_decay != 0 and self.steps >= 20 * self.TCov:
                    d_p.add_(weight_decay, p.data)
                if momentum != 0:
                    param_state = self.state[p]
                    if 'momentum_buffer' not in param_state:
                        buf = param_state['momentum_buffer'] = torch.zeros_like(
                            p.data)
                        try:
                            buf.mul_(momentum).add_(d_p)
                        except RuntimeError:
                            buf.mul_(momentum).add_(d_p.squeeze(0))
                    else:
                        buf = param_state['momentum_buffer']
                        try:
                            buf.mul_(momentum).add_(d_p)
                        except RuntimeError:
                            buf.mul_(momentum).add_(d_p.squeeze(0))
                    d_p = buf

                torch.add(p.data, -lr, d_p, out=p.data)

    @torch.no_grad()
    def step(self, closure: Optional[Callable] = None):
        """
        This is the function that gets called in each step of the optimizer to update the weights and biases of the model.

        Parameters:
        -----------
        closure: Callable, optional(default: None)
          an optional customizable function to be passed which can be used to clear the gradients and other compute loss for every step.
        """
        group = self.param_groups[0]
        lr = group['lr']
        damping = group['damping']
        updates = {}
        for m in self.modules:
            if self.steps % self.TInv == 0:
                self._update_inv(m)
            p_grad_mat = self.get_matrix_form_grad(m)
            v = self._get_natural_grad(m, p_grad_mat, damping)
            updates[m] = v
        self._kl_clip_and_update_grad(updates, lr)
        self._step(closure)
        self.steps += 1
        self.input_number_forward = 0
        self.input_number_backward = 0
