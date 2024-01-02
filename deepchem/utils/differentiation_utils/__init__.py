# flake8: noqa
try:
    from deepchem.utils.differentiation_utils.editable_module import EditableModule

    from deepchem.utils.differentiation_utils.bcast import normalize_bcast_dims
    from deepchem.utils.differentiation_utils.bcast import get_bcasted_dims
    from deepchem.utils.differentiation_utils.bcast import match_dim

    from deepchem.utils.differentiation_utils.misc import set_default_option
    from deepchem.utils.differentiation_utils.misc import get_and_pop_keys
    from deepchem.utils.differentiation_utils.misc import get_method
    from deepchem.utils.differentiation_utils.misc import dummy_context_manager
    from deepchem.utils.differentiation_utils.misc import assert_runtime

    from deepchem.utils.differentiation_utils.linop import LinearOperator
    from deepchem.utils.differentiation_utils.linop import AddLinearOperator
    from deepchem.utils.differentiation_utils.linop import MulLinearOperator
    from deepchem.utils.differentiation_utils.linop import AdjointLinearOperator
    from deepchem.utils.differentiation_utils.linop import MatmulLinearOperator
    from deepchem.utils.differentiation_utils.linop import MatrixLinearOperator

    from deepchem.utils.differentiation_utils.solve import wrap_gmres
    from deepchem.utils.differentiation_utils.solve import exactsolve
    from deepchem.utils.differentiation_utils.solve import solve_ABE
    from deepchem.utils.differentiation_utils.solve import get_batchdims
    from deepchem.utils.differentiation_utils.solve import setup_precond
    from deepchem.utils.differentiation_utils.solve import dot
    from deepchem.utils.differentiation_utils.solve import get_largest_eival
    from deepchem.utils.differentiation_utils.solve import safedenom
    from deepchem.utils.differentiation_utils.solve import setup_linear_problem
    from deepchem.utils.differentiation_utils.solve import gmres    
except:
    pass
