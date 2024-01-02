import pytest
try:
    import torch
    from deepchem.utils.differentiation_utils import EditableModule
    has_torch = True
except ModuleNotFoundError:
    has_torch = False


@pytest.mark.torch
def test_getparams():

    class A(EditableModule):

        def __init__(self, a):
            self.b = a * a

        def mult(self, x):
            return self.b * x

        def getparamnames(self, methodname, prefix=""):
            if methodname == "mult":
                return [prefix + "b"]
            else:
                raise KeyError()

    a = torch.tensor(2.0)
    x = torch.tensor(0.4)
    alpha = A(a)
    assert alpha.mult(x) == torch.tensor(1.6)
    assert alpha.getparams("mult") == [torch.tensor(4.)]


@pytest.mark.torch
def test_setparams():

    class A(EditableModule):

        def __init__(self, a):
            self.b = a * a

        def mult(self, x):
            return self.b * x

        def getparamnames(self, methodname, prefix=""):
            if methodname == "mult":
                return [prefix + "b"]
            else:
                raise KeyError()

    a = torch.tensor(2.0)
    x = torch.tensor(4.0)
    alpha = A(a)
    assert alpha.mult(x) == torch.tensor(16)
    alpha.setparams("mult", torch.tensor(5.0))
    assert alpha.mult(x) == torch.tensor(20.0)


@pytest.mark.torch
def test_cached_getparamnames():

    class A(EditableModule):

        def __init__(self, a):
            self.b = a * a

        def mult(self, x):
            return self.b * x

        def getparamnames(self, methodname, prefix=""):
            if methodname == "mult":
                return [prefix + "b"]
            else:
                raise KeyError()

    a = torch.tensor(2.0)
    alpha = A(a)
    assert alpha.cached_getparamnames("mult") == ["b"]


@pytest.mark.torch
def test_getuniqueparams():

    class A(EditableModule):

        def __init__(self, a):
            self.b = a * a

        def mult(self, x):
            return self.b**2 * x

        def getparamnames(self, methodname, prefix=""):
            if methodname == "mult":
                return [prefix + "b"]
            else:
                raise KeyError()

    a = torch.tensor(2.0)
    x = torch.tensor(0.4)
    alpha = A(a)
    assert alpha.mult(x) == torch.tensor(6.4)
    assert alpha.getuniqueparams("mult") == [torch.tensor(4.)]  # Not 16.0


@pytest.mark.torch
def test_setuniqueparams():

    class A(EditableModule):

        def __init__(self, a):
            self.b = a * a

        def mult(self, x):
            return self.b**2 * x

        def getparamnames(self, methodname, prefix=""):
            if methodname == "mult":
                return [prefix + "b"]
            else:
                raise KeyError()

    a = torch.tensor(2.0)
    x = torch.tensor(0.4)
    alpha = A(a)
    assert alpha.mult(x) == torch.tensor(6.4)
    assert alpha.getuniqueparams("mult") == [torch.tensor(4.)]
    alpha.setuniqueparams("mult", torch.tensor(5.0))
    assert alpha.mult(x) == torch.tensor(10.0)


@pytest.mark.torch
def test_get_unique_params_idxs():

    class A(EditableModule):

        def __init__(self, a):
            self.b = a * a
            self.c = a * a * a

        def mult(self, x):
            return self.b * self.c * x

        def getparamnames(self, methodname, prefix=""):
            if methodname == "mult":
                return [prefix + "b", prefix + "c"]
            else:
                raise KeyError()

    a = torch.tensor(2.0)
    x = torch.tensor(4.0)
    alpha = A(a)
    assert alpha.mult(x) == torch.tensor(128.0)
    assert alpha.getparams("mult") == [torch.tensor(4.), torch.tensor(8.)]
    assert alpha._get_unique_params_idxs("mult") == [0, 1]


@pytest.mark.torch
def test_assertparams():
    """Test that assertparams works correctly.
    also checks the private methods as they are used in it.
    - __assert_method_preserve
    - __assert_get_correct_params
    - __list_operating_params

    """

    class A(EditableModule):

        def __init__(self, a):
            self.b = a * a
            self.c = a * a * a

        def mult(self, x):
            return self.b * self.c * x

        def getparamnames(self, methodname, prefix=""):
            if methodname == "mult":
                return [prefix + "b", prefix + "c"]
            else:
                raise KeyError()

    a = torch.tensor(2.0)
    x = torch.tensor(4.0)
    alpha = A(a)
    assert alpha.mult(x) == torch.tensor(128.0)
    assert alpha.getparams("mult") == [torch.tensor(4.), torch.tensor(8.)]
    alpha.assertparams(alpha.mult, x)


@pytest.mark.torch
def test_getparamnames():

    class A(EditableModule):

        def __init__(self, a):
            self.b = a * a

        def mult(self, x):
            return self.b * x

        def getparamnames(self, methodname, prefix=""):
            if methodname == "mult":
                return [prefix + "b"]
            else:
                raise KeyError()

    a = torch.tensor(2.0).requires_grad_()
    x = torch.tensor(0.4).requires_grad_()
    alpha = A(a)
    assert alpha.mult(x) == torch.tensor(1.6000)
    assert alpha.getparamnames("mult") == ['b']


@pytest.mark.torch
def test_traverse_obj():
    from deepchem.utils.differentiation_utils.editable_module import _traverse_obj, torch_float_type

    class A:

        def __init__(self):
            self.a = 2
            self.b = torch.tensor(3.0)
            self.c = torch.tensor(4.0)
            self.d = torch.tensor(5.0)

    a = A()

    def action(elmt, name, objdict, key):
        print(name, elmt)

    def crit(elmt):
        return isinstance(elmt, torch.Tensor) and elmt.dtype in torch_float_type

    a = _traverse_obj(a, "", action, crit)  # Check Doesn't Crashes


@pytest.mark.torch
def test_get_tensor():
    from deepchem.utils.differentiation_utils.editable_module import _get_tensors

    class A:

        def __init__(self):
            self.a = 2
            self.b = torch.tensor(3.0)
            self.c = torch.tensor(4.0)
            self.d = torch.tensor(5.0)

    a = A()
    outputs = _get_tensors(a)
    assert outputs[0] == [torch.tensor(3.), torch.tensor(4.), torch.tensor(5.)]
    assert outputs[1] == ['b', 'c', 'd']


@pytest.mark.torch
def test_set_tensor():
    from deepchem.utils.differentiation_utils.editable_module import _set_tensors

    class A:

        def __init__(self):
            self.a = 2
            self.b = torch.tensor(3.0)
            self.c = torch.tensor(4.0)
            self.d = torch.tensor(5.0)

    a = A()
    _set_tensors(a, [torch.tensor(6.), torch.tensor(7.), torch.tensor(8.)])
    assert a.b == torch.tensor(6.)
    assert a.c == torch.tensor(7.)


@pytest.mark.torch
def test_normalize_bcast_dims():
    from deepchem.utils.differentiation_utils import normalize_bcast_dims
    assert normalize_bcast_dims([1, 2, 3], [2, 3]) == [[1, 2, 3], [1, 2, 3]]


@pytest.mark.torch
def test_get_bcasted_dims():
    from deepchem.utils.differentiation_utils import get_bcasted_dims
    assert get_bcasted_dims([1, 2, 5], [2, 3, 4]) == [2, 3, 5]


@pytest.mark.torch
def test_match_dim():
    from deepchem.utils.differentiation_utils import match_dim
    x = torch.randn(10, 5)
    xq = torch.randn(10, 3)
    x_new, xq_new = match_dim(x, xq)
    assert x_new.shape == torch.Size([10, 5])
    assert xq_new.shape == torch.Size([10, 3])


@pytest.mark.torch
def test_linear_operator():
    from deepchem.utils.differentiation_utils import LinearOperator
    torch.manual_seed(100)

    class MyLinOp(LinearOperator):

        def __init__(self, shape):
            super(MyLinOp, self).__init__(shape)
            self.param = torch.rand(shape)

        def _getparamnames(self, prefix=""):
            return [prefix + "param"]

        def _mv(self, x):
            return torch.matmul(self.param, x)

        def _rmv(self, x):
            return torch.matmul(self.param.transpose(-2, -1).conj(), x)

        def _mm(self, x):
            return torch.matmul(self.param, x)

        def _rmm(self, x):
            return torch.matmul(self.param.transpose(-2, -1).conj(), x)

        def _fullmatrix(self):
            return self.param

    linop = MyLinOp((1, 3, 1, 2))
    x = torch.rand(1, 3, 2, 2)
    assert torch.allclose(linop.mv(x), torch.matmul(linop.param, x))
    x = torch.rand(1, 3, 1, 1)
    assert torch.allclose(linop.rmv(x),
                          torch.matmul(linop.param.transpose(-2, -1).conj(), x))
    x = torch.rand(1, 3, 2, 2)
    assert torch.allclose(linop.mm(x), torch.matmul(linop.param, x))
    x = torch.rand(1, 3, 1, 2)
    assert torch.allclose(linop.rmm(x),
                          torch.matmul(linop.param.transpose(-2, -1).conj(), x))
    assert torch.allclose(linop.fullmatrix(), linop.param)


@pytest.mark.torch
def test_add_linear_operator():
    from deepchem.utils.differentiation_utils import LinearOperator

    class Operator(LinearOperator):

        def __init__(self, mat: torch.Tensor, is_hermitian: bool) -> None:
            super(Operator, self).__init__(
                shape=mat.shape,
                is_hermitian=is_hermitian,
                dtype=mat.dtype,
                device=mat.device,
                _suppress_hermit_warning=True,
            )
            self.mat = mat

        def _mv(self, x: torch.Tensor) -> torch.Tensor:
            return torch.matmul(self.mat, x.unsqueeze(-1)).squeeze(-1)

        def _mm(self, x: torch.Tensor) -> torch.Tensor:
            return torch.matmul(self.mat, x)

        def _rmv(self, x: torch.Tensor) -> torch.Tensor:
            return torch.matmul(
                self.mat.transpose(-3, -1).conj(), x.unsqueeze(-1)).squeeze(-1)

        def _rmm(self, x: torch.Tensor) -> torch.Tensor:
            return torch.matmul(self.mat.transpose(-2, -1).conj(), x)

        def _fullmatrix(self) -> torch.Tensor:
            return self.mat

        def _getparamnames(self, prefix: str = ""):
            return [prefix + "mat"]

    op = Operator(torch.tensor([[1, 2.], [3, 4]]), is_hermitian=False)
    x = torch.tensor([[2, 2], [1, 2.]])
    op2 = op + op
    assert torch.allclose(op2.mm(x), 2 * op.mm(x))


@pytest.mark.torch
def test_mul_linear_operator():
    from deepchem.utils.differentiation_utils import LinearOperator

    class MyLinOp(LinearOperator):

        def __init__(self, shape):
            super(MyLinOp, self).__init__(shape)
            self.param = torch.rand(shape)

        def _getparamnames(self, prefix=""):
            return [prefix + "param"]

        def _mv(self, x):
            return torch.matmul(self.param, x)

    linop = MyLinOp((1, 3, 1, 2))
    linop2 = linop * 2
    x = torch.rand(1, 3, 2, 2)
    torch.allclose(linop.mv(x) * 2, linop2.mv(x))


@pytest.mark.torch
def test_adjoint_linear_operator():
    from deepchem.utils.differentiation_utils import LinearOperator

    class MyLinOp(LinearOperator):

        def __init__(self, shape):
            super(MyLinOp, self).__init__(shape)
            self.param = torch.rand(shape)

        def _getparamnames(self, prefix=""):
            return [prefix + "param"]

        def _mv(self, x):
            return torch.matmul(self.param, x)

        def _rmv(self, x):
            return torch.matmul(self.param.transpose(-2, -1).conj(), x)

    linop = MyLinOp((1, 3, 1, 2))
    x = torch.rand(1, 3, 1, 1)
    result_rmv = linop.rmv(x)

    adjoint_linop = linop.H
    result_mv = adjoint_linop.mv(x)

    assert torch.allclose(result_rmv, result_mv)


@pytest.mark.torch
def test_matmul_linear_operator():
    from deepchem.utils.differentiation_utils import LinearOperator

    class MyLinOp(LinearOperator):

        def __init__(self, shape):
            super(MyLinOp, self).__init__(shape)
            self.param = torch.rand(shape)

        def _getparamnames(self, prefix=""):
            return [prefix + "param"]

        def _mv(self, x):
            return torch.matmul(self.param, x)

    linop1 = MyLinOp((1, 3, 1, 2))
    linop2 = MyLinOp((1, 3, 2, 1))
    linop_result = linop1.matmul(linop2)
    x = torch.rand(1, 3, 1, 1)
    result = linop_result.mv(x)
    assert result.shape == torch.Size([1, 3, 1, 1])


@pytest.mark.torch
def test_matrix_linear_operator():
    from deepchem.utils.differentiation_utils import LinearOperator

    mat = torch.rand(2, 2)
    linop = LinearOperator.m(mat)
    x = torch.randn(2, 2)

    result_mm = linop.mm(x)
    expected_mm = torch.matmul(mat, x)

    result_mv = linop.mv(x)
    expected_mv = torch.matmul(mat, x.unsqueeze(-1)).squeeze(-1)

    assert torch.allclose(result_mm, expected_mm)
    assert torch.allclose(result_mv, expected_mv)


def test_set_default_options():
    from deepchem.utils.differentiation_utils import set_default_option
    assert set_default_option({'a': 1, 'b': 2}, {'a': 3}) == {'a': 3, 'b': 2}


def test_get_and_pop_keys():
    from deepchem.utils.differentiation_utils import get_and_pop_keys
    assert get_and_pop_keys({'a': 1, 'b': 2}, ['a']) == {'a': 1}


def test_get_method():
    from deepchem.utils.differentiation_utils import get_method
    assert get_method('foo', {'bar': lambda: 1}, 'bar')() == 1


def test_dummy_context_manager():
    """Just checks that dummy_context_manager doesn't crash"""
    from deepchem.utils.differentiation_utils import dummy_context_manager
    with dummy_context_manager() as x:
        if x is None:
            pass
        else:
            raise AssertionError()


def test_assert_runtime():
    from deepchem.utils.differentiation_utils import assert_runtime
    try:
        assert_runtime(False, "This should fail")
    except RuntimeError:
        pass


@pytest.mark.torch
def test_wrap_gmres():
    from deepchem.utils.differentiation_utils.solve import wrap_gmres
    from deepchem.utils.differentiation_utils import LinearOperator
    A = LinearOperator.m(torch.tensor([[1., 2], [3, 4]]))
    B = torch.tensor([[[5., 6], [7, 8]]])
    assert torch.allclose(A.fullmatrix() @ wrap_gmres(A, B, None, None), B)


@pytest.mark.torch
def test_exact_solve():
    from deepchem.utils.differentiation_utils.solve import exactsolve
    from deepchem.utils.differentiation_utils import LinearOperator
    A = LinearOperator.m(torch.tensor([[1., 2], [3, 4]]))
    B = torch.tensor([[5., 6], [7, 8]])
    assert torch.allclose(A.fullmatrix() @ exactsolve(A, B, None, None), B)


@pytest.mark.torch
def test_solve_ABE():
    from deepchem.utils.differentiation_utils.solve import solve_ABE
    A = torch.tensor([[1., 2], [3, 4]])
    B = torch.tensor([[5., 6], [7, 8]])
    E = torch.tensor([1., 2])
    expected_result = torch.tensor([[-0.1667, 0.5000], [2.5000, 3.2500]])
    assert torch.allclose(solve_ABE(A, B, E), expected_result, 0.001)


@pytest.mark.torch
def test_get_batch_dims():
    from deepchem.utils.differentiation_utils.solve import get_batchdims
    from deepchem.utils.differentiation_utils import MatrixLinearOperator
    A = MatrixLinearOperator(torch.randn(4, 3, 3), True)
    B = torch.randn(3, 3, 2)
    assert get_batchdims(A, B, None,
                         None) == [max(A.shape[:-2], B.shape[:-2])[0]]


@pytest.mark.torch
def test_setup_precond():
    from deepchem.utils.differentiation_utils.solve import setup_precond
    from deepchem.utils.differentiation_utils import MatrixLinearOperator
    A = MatrixLinearOperator(torch.randn(4, 3, 3), True)
    B = torch.randn(4, 3, 2)
    cond = setup_precond(A)
    assert cond(B).shape == torch.Size([4, 3, 2])


@pytest.mark.torch
def test_dot():
    from deepchem.utils.differentiation_utils.solve import dot
    r = torch.tensor([[1, 2], [3, 4]])
    z = torch.tensor([[5, 6], [7, 8]])
    assert torch.allclose(dot(r, z), torch.tensor([[26, 44]]))
    assert torch.allclose(dot(r, z), sum(r * z))


@pytest.mark.torch
def test_gmres():
    from deepchem.utils.differentiation_utils.solve import gmres
    from deepchem.utils.differentiation_utils import MatrixLinearOperator
    A = MatrixLinearOperator(torch.tensor([[1., 2], [3, 4]]), True)
    B = torch.tensor([[5., 6], [7, 8]])
    expected_result = torch.tensor([[0.8959, 1.0697], [1.2543, 1.4263]])
    assert torch.allclose(gmres(A, B), expected_result, 0.001)


@pytest.mark.torch
def test_setup_linear_problem():
    from deepchem.utils.differentiation_utils import MatrixLinearOperator
    from deepchem.utils.differentiation_utils.solve import setup_linear_problem
    A = MatrixLinearOperator(torch.randn(4, 3, 3), True)
    B = torch.randn(4, 3, 2)
    A_fcn, AT_fcn, B_new, col_swapped = setup_linear_problem(
        A, B, None, None, [4], None, False)
    assert A_fcn(B).shape == torch.Size([4, 3, 2])


@pytest.mark.torch
def test_safe_denom():
    from deepchem.utils.differentiation_utils.solve import safedenom
    r = torch.tensor([[0., 2], [3, 4]])
    assert torch.allclose(
        safedenom(r, 1e-9),
        torch.tensor([[1.0000e-09, 2.0000e+00], [3.0000e+00, 4.0000e+00]]))


@pytest.mark.torch
def test_get_largest_eival():
    from deepchem.utils.differentiation_utils.solve import get_largest_eival

    def Afcn(x):
        return 10 * x

    x = torch.tensor([[1., 2], [3, 4]])
    assert torch.allclose(get_largest_eival(Afcn, x), torch.tensor([[10.,
                                                                     10.]]))
