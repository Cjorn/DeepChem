import numpy as np
import torch
import warnings
from typing import Sequence, Tuple, Union, Optional, Callable
from deepchem.utils.differentiation_utils import LinearOperator, normalize_bcast_dims, get_bcasted_dims
from deepchem.utils import ConvergenceWarning, get_np_dtype
from scipy.sparse.linalg import gmres as scipy_gmres


# Hidden
def wrap_gmres(A, B, E=None, M=None, min_eps=1e-9, max_niter=None, **unused):
    """
    Using SciPy's gmres method to solve the linear equation.

    Examples
    --------
    >>> import torch
    >>> from deepchem.utils.differentiation_utils import LinearOperator
    >>> A = LinearOperator.m(torch.tensor([[1., 2], [3, 4]]))
    >>> B = torch.tensor([[[5., 6], [7, 8]]])
    >>> wrap_gmres(A, B, None, None)
    tensor([[[-3.0000, -4.0000],
             [ 4.0000,  5.0000]]])

    Parameters
    ----------
    A: LinearOperator
        The linear operator A to be solved. Shape: (*BA, na, na)
    B: torch.Tensor
        Batched matrix B. Shape: (*BB, na, ncols)
    E: torch.Tensor or None
        Batched vector E. Shape: (*BE, ncols)
    M: LinearOperator or None
        The linear operator M. Shape: (*BM, na, na)
    min_eps: float
        Relative tolerance for stopping conditions
    max_niter: int or None
        Maximum number of iterations. If ``None``, default to twice of the
        number of columns of ``A``.

    Returns
    -------
    torch.Tensor
        The Solution matrix X. Shape: (*BBE, na, ncols)

    """

    # NOTE: currently only works for batched B (1 batch dim), but unbatched A
    assert len(A.shape) == 2 and len(
        B.shape
    ) == 3, "Currently only works for batched B (1 batch dim), but unbatched A"
    assert not torch.is_complex(B), "complex is not supported in gmres"

    # check the parameters
    msg = "GMRES can only do AX=B"
    assert A.shape[-2] == A.shape[
        -1], "GMRES can only work for square operator for now"
    assert E is None, msg
    assert M is None, msg

    nbatch, na, ncols = B.shape
    if max_niter is None:
        max_niter = 2 * na

    B = B.transpose(-1, -2)  # (nbatch, ncols, na)

    # convert the numpy/scipy
    op = A.scipy_linalg_op()
    B_np = B.detach().cpu().numpy()
    res_np = np.empty(B.shape, dtype=get_np_dtype(B.dtype))
    for i in range(nbatch):
        for j in range(ncols):
            x, info = scipy_gmres(op,
                                  B_np[i, j, :],
                                  tol=min_eps,
                                  atol=1e-12,
                                  maxiter=max_niter)
            if info > 0:
                msg = "The GMRES iteration does not converge to the desired value "\
                      "(%.3e) after %d iterations" % \
                      (min_eps, info)
                warnings.warn(ConvergenceWarning(msg))
            res_np[i, j, :] = x

    res = torch.tensor(res_np, dtype=B.dtype, device=B.device)
    res = res.transpose(-1, -2)  # (nbatch, na, ncols)
    return res


def exactsolve(A: LinearOperator, B: torch.Tensor, E: Union[torch.Tensor, None],
               M: Union[LinearOperator, None]):
    """
    Solve the linear equation by contructing the full matrix of LinearOperators.

    Examples
    --------
    >>> import torch
    >>> from deepchem.utils.differentiation_utils import LinearOperator
    >>> A = LinearOperator.m(torch.tensor([[1., 2], [3, 4]]))
    >>> B = torch.tensor([[5., 6], [7, 8]])
    >>> exactsolve(A, B, None, None)
    tensor([[-3., -4.],
            [ 4.,  5.]])

    Parameters
    ----------
    A: LinearOperator
        The linear operator A to be solved. Shape: (*BA, na, na)
    B: torch.Tensor
        Batched matrix B. Shape: (*BB, na, ncols)
    E: torch.Tensor or None
        Batched vector E. Shape: (*BE, ncols)
    M: LinearOperator or None
        The linear operator M. Shape: (*BM, na, na)

    Returns
    -------
    torch.Tensor
        The Solution matrix X. Shape: (*BBE, na, ncols)

    Warnings
    --------
    * As this method construct the linear operators explicitly, it might requires
      a large memory.

    """
    if E is None:
        Amatrix = A.fullmatrix()
        x = torch.linalg.solve(Amatrix, B)
    elif M is None:
        Amatrix = A.fullmatrix()
        x = solve_ABE(Amatrix, B, E)
    else:
        Mmatrix = M.fullmatrix()
        L = torch.linalg.cholesky(Mmatrix)
        Linv = torch.inverse(L)
        LinvT = Linv.transpose(-2, -1).conj()
        A2 = torch.matmul(Linv, A.mm(LinvT))
        B2 = torch.matmul(Linv, B)

        X2 = solve_ABE(A2, B2, E)
        x = torch.matmul(LinvT, X2)
    return x


def solve_ABE(A: torch.Tensor, B: torch.Tensor, E: torch.Tensor):
    """ Solve the linear equation AX = B - diag(E)X.

    Examples
    --------
    >>> import torch
    >>> A = torch.tensor([[1., 2], [3, 4]])
    >>> B = torch.tensor([[5., 6], [7, 8]])
    >>> E = torch.tensor([1., 2])
    >>> solve_ABE(A, B, E)
    tensor([[-0.1667,  0.5000],
            [ 2.5000,  3.2500]])

    Parameters
    ----------
    A: torch.Tensor
        The batched matrix A. Shape: (*BA, na, na)
    B: torch.Tensor
        The batched matrix B. Shape: (*BB, na, ncols)
    E: torch.Tensor
        The batched vector E. Shape: (*BE, ncols)

    Returns
    -------
    torch.Tensor
        The batched matrix X.

    """
    na = A.shape[-1]
    BA, BB, BE = normalize_bcast_dims(A.shape[:-2], B.shape[:-2], E.shape[:-1])
    E = E.reshape(1, *BE, E.shape[-1]).transpose(0, -1)  # (ncols, *BE, 1)
    B = B.reshape(1, *BB, *B.shape[-2:]).transpose(0, -1)  # (ncols, *BB, na, 1)

    # NOTE: The line below is very inefficient for large na and ncols
    AE = A - torch.diag_embed(E.repeat_interleave(repeats=na, dim=-1),
                              dim1=-2,
                              dim2=-1)  # (ncols, *BAE, na, na)
    r = torch.linalg.solve(AE, B)  # (ncols, *BAEM, na, 1)
    r = r.transpose(0, -1).squeeze(0)  # (*BAEM, na, ncols)
    return r


# general helpers
def get_batchdims(A: LinearOperator, B: torch.Tensor,
                  E: Union[torch.Tensor, None], M: Union[LinearOperator, None]):
    """Get the batch dimensions of the linear operator and the matrix B

    Examples
    --------
    >>> from deepchem.utils.differentiation_utils import MatrixLinearOperator
    >>> import torch
    >>> A = MatrixLinearOperator(torch.randn(4, 3, 3), True)
    >>> B = torch.randn(3, 3, 2)
    >>> get_batchdims(A, B, None, None)
    [4]

    Parameters
    ----------
    A: LinearOperator
        The linear operator. It can be a batched linear operator.
    B: torch.Tensor
        The matrix B. It can be a batched matrix.
    E: Union[torch.Tensor, None]
        The matrix E. It can be a batched matrix.
    M: Union[LinearOperator, None]
        The linear operator M. It can be a batched linear operator.

    Returns
    -------
    List[int]
        The batch dimensions of the linear operator and the matrix B

    """

    batchdims = [A.shape[:-2], B.shape[:-2]]
    if E is not None:
        batchdims.append(E.shape[:-1])
        if M is not None:
            batchdims.append(M.shape[:-2])
    return get_bcasted_dims(*batchdims)


def setup_precond(
    precond: Optional[LinearOperator] = None
) -> Callable[[torch.Tensor], torch.Tensor]:
    """Setup the preconditioning function

    Examples
    --------
    >>> from deepchem.utils.differentiation_utils import MatrixLinearOperator
    >>> import torch
    >>> A = MatrixLinearOperator(torch.randn(4, 3, 3), True)
    >>> B = torch.randn(4, 3, 2)
    >>> cond = setup_precond(A)
    >>> cond(B).shape
    torch.Size([4, 3, 2])

    Parameters
    ----------
    precond: Optional[LinearOperator]
        The preconditioning linear operator. If None, no preconditioning is
        applied.

    Returns
    -------
    Callable[[torch.Tensor], torch.Tensor]
        The preconditioning function. It takes a tensor and returns a tensor.

    """
    if isinstance(precond, LinearOperator):

        def precond_fcn(x):
            return precond.mm(x)
    elif precond is None:

        def precond_fcn(x):
            return x
    else:
        raise TypeError("precond can only be LinearOperator or None")
    return precond_fcn


def _setup_linear_problem(A: LinearOperator, B: torch.Tensor,
                          E: Optional[torch.Tensor], M: Optional[LinearOperator],
                          batchdims: Sequence[int],
                          posdef: Optional[bool],
                          need_hermit: bool) -> \
        Tuple[Callable[[torch.Tensor], torch.Tensor],
              Callable[[torch.Tensor], torch.Tensor],
              torch.Tensor, bool]:
    """Setup the linear problem for solving AX = B

    Examples
    --------
    >>> from deepchem.utils.differentiation_utils import MatrixLinearOperator
    >>> import torch
    >>> A = MatrixLinearOperator(torch.randn(4, 3, 3), True)
    >>> B = torch.randn(4, 3, 2)
    >>> A_fcn, AT_fcn, B_new, col_swapped = _setup_linear_problem(A, B, None, None, [4], None, False)
    >>> A_fcn(B).shape
    torch.Size([4, 3, 2])

    Parameters
    ----------
    A: LinearOperator
        The linear operator A. It can be a batched linear operator.
    B: torch.Tensor
        The matrix B. It can be a batched matrix.
    E: Optional[torch.Tensor]
        The matrix E. It can be a batched matrix.
    M: Optional[LinearOperator]
        The linear operator M. It can be a batched linear operator.
    batchdims: Sequence[int]
        The batch dimensions of the linear operator and the matrix B
    posdef: Optional[bool]
        Whether the linear operator is positive definite. If None, it will be
        estimated.
    need_hermit: bool
        Whether the linear operator is Hermitian. If True, it will be estimated.

    Returns
    -------
    Tuple[Callable[[torch.Tensor], torch.Tensor],
          Callable[[torch.Tensor], torch.Tensor],
          torch.Tensor, bool]
        The function A, its transposed function, the matrix B, and whether the
        columns of B are swapped.

    """

    # get the linear operator (including the MXE part)
    if E is None:

        def A_fcn(x):
            return A.mm(x)

        def AT_fcn(x):
            return A.rmm(x)

        B_new = B
        col_swapped = False
    else:
        # A: (*BA, nr, nr) linop
        # B: (*BB, nr, ncols)
        # E: (*BE, ncols)
        # M: (*BM, nr, nr) linop
        if M is None:
            BAs, BBs, BEs = normalize_bcast_dims(A.shape[:-2], B.shape[:-2],
                                                 E.shape[:-1])
        else:
            BAs, BBs, BEs, BMs = normalize_bcast_dims(A.shape[:-2],
                                                      B.shape[:-2],
                                                      E.shape[:-1],
                                                      M.shape[:-2])
        E = E.reshape(*BEs, *E.shape[-1:])
        E_new = E.unsqueeze(0).transpose(-1,
                                         0).unsqueeze(-1)  # (ncols, *BEs, 1, 1)
        B = B.reshape(*BBs, *B.shape[-2:])  # (*BBs, nr, ncols)
        B_new = B.unsqueeze(0).transpose(-1, 0)  # (ncols, *BBs, nr, 1)

        def A_fcn(x):
            # x: (ncols, *BX, nr, 1)
            Ax = A.mm(x)  # (ncols, *BAX, nr, 1)
            Mx = M.mm(x) if M is not None else x  # (ncols, *BMX, nr, 1)
            MxE = Mx * E_new  # (ncols, *BMXE, nr, 1)
            return Ax - MxE

        def AT_fcn(x):
            # x: (ncols, *BX, nr, 1)
            ATx = A.rmm(x)
            MTx = M.rmm(x) if M is not None else x
            MTxE = MTx * E_new
            return ATx - MTxE

        col_swapped = True

    # estimate if it's posdef with power iteration
    if need_hermit:
        is_hermit = A.is_hermitian and (M is None or M.is_hermitian)
        if not is_hermit:
            # set posdef to False to make the operator becomes AT * A so it is
            # hermitian
            posdef = False

    # TODO: the posdef check by largest eival only works for Hermitian/symmetric
    # matrix, but it doesn't always work for non-symmetric matrix.
    # In non-symmetric case, one need to do Cholesky LDL decomposition
    if posdef is None:
        nr, ncols = B.shape[-2:]
        x0shape = (ncols, *batchdims, nr, 1) if col_swapped else (*batchdims,
                                                                  nr, ncols)
        x0 = torch.randn(x0shape, dtype=A.dtype, device=A.device)
        x0 = x0 / x0.norm(dim=-2, keepdim=True)
        largest_eival = _get_largest_eival(A_fcn, x0)  # (*, 1, nc)
        negeival = largest_eival <= 0

        # if the largest eigenvalue is negative, then it's not posdef
        if torch.all(negeival):
            posdef = False

        # otherwise, calculate the lowest eigenvalue to check if it's positive
        else:
            offset = torch.clamp(largest_eival, min=0.0)

            def A_fcn2(x):
                return A_fcn(x) - offset * x

            mostneg_eival = _get_largest_eival(A_fcn2, x0)  # (*, 1, nc)
            posdef = bool(
                torch.all(torch.logical_or(-mostneg_eival <= offset,
                                           negeival)).item())

    # get the linear operation if it is not a posdef (A -> AT.A)
    if posdef:
        return A_fcn, AT_fcn, B_new, col_swapped
    else:

        def A_new_fcn(x):
            return AT_fcn(A_fcn(x))

        B2 = AT_fcn(B_new)
        return A_new_fcn, A_new_fcn, B2, col_swapped


# cg and bicgstab helpers
def _safedenom(r: torch.Tensor, eps: float) -> torch.Tensor:
    """Make sure the denominator is not zero

    Examples
    --------
    >>> import torch
    >>> r = torch.tensor([[0., 2], [3, 4]])
    >>> _safedenom(r, 1e-9)
    tensor([[1.0000e-09, 2.0000e+00],
            [3.0000e+00, 4.0000e+00]])

    Parameters
    ----------
    r: torch.Tensor
        The input tensor. Shape: (*BR, nr, nc)
    eps: float
        The small number to replace the zero denominator

    Returns
    -------
    torch.Tensor
        The tensor with non-zero denominator. Shape: (*BR, nr, nc)

    """
    r[r == 0] = eps
    return r


def dot(r: torch.Tensor, z: torch.Tensor) -> torch.Tensor:
    """Dot product of two vectors. r and z must have the same shape.
    Then sums it up across the last dimension.

    Examples
    --------
    >>> import torch
    >>> r = torch.tensor([[1, 2], [3, 4]])
    >>> z = torch.tensor([[5, 6], [7, 8]])
    >>> dot(r, z)
    tensor([[26, 44]])

    Parameters
    ----------
    r: torch.Tensor
        The first vector. Shape: (*BR, nr, nc)
    z: torch.Tensor
        The second vector. Shape: (*BR, nr, nc)

    Returns
    -------
    torch.Tensor
        The dot product of r and z. Shape: (*BR, 1, nc)

    """
    return torch.einsum("...rc,...rc->...c", r.conj(), z).unsqueeze(-2)


def _get_largest_eival(Afcn: Callable, x: torch.Tensor) -> torch.Tensor:
    """Get the largest eigenvalue of the linear operator Afcn

    Examples
    --------
    >>> import torch
    >>> def Afcn(x):
    ...     return 10 * x
    >>> x = torch.tensor([[1., 2], [3, 4]])
    >>> _get_largest_eival(Afcn, x)
    tensor([[10., 10.]])

    Parameters
    ----------
    Afcn: Callable
        The linear operator A. It takes a tensor and returns a tensor.
    x: torch.Tensor
        The input tensor. Shape: (*, nr, nc)

    Returns
    -------
    torch.Tensor
        The largest eigenvalue. Shape: (*, 1, nc)

    """
    niter = 10
    rtol = 1e-3
    atol = 1e-6
    xnorm_prev = None
    for i in range(niter):
        x = Afcn(x)  # (*, nr, nc)
        xnorm = x.norm(dim=-2, keepdim=True)  # (*, 1, nc)

        # check if xnorm is converging
        if i > 0:
            dnorm = torch.abs(xnorm_prev - xnorm)
            if torch.all(dnorm <= rtol * xnorm + atol):
                break

        xnorm_prev = xnorm
        if i < niter - 1:
            x = x / xnorm
    return xnorm
