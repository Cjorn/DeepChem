import numpy as np
import pytest
try:
    import torch
    has_torch = True
except ModuleNotFoundError:
    has_torch = False

from deepchem.utils.pytorch_utils import unsorted_segment_sum
from deepchem.utils.pytorch_utils import segment_sum


@pytest.mark.torch
def test_unsorted_segment_sum():

    segment_ids = torch.Tensor([0, 1, 0]).to(torch.int64)
    data = torch.Tensor([[1, 2, 3, 4], [5, 6, 7, 8], [4, 3, 2, 1]])
    num_segments = 2

    result = unsorted_segment_sum(data=data,
                                  segment_ids=segment_ids,
                                  num_segments=num_segments)

    assert np.allclose(np.array(result),
                       np.load("assets/result_segment_sum.npy"),
                       atol=1e-04)


@pytest.mark.torch
def test_segment_sum():

    data = torch.Tensor([[1, 2, 3, 4], [4, 3, 2, 1], [5, 6, 7, 8]])
    segment_ids = torch.Tensor([0, 0, 1]).to(torch.int64)

    result = segment_sum(data=data, segment_ids=segment_ids)

    assert np.allclose(np.array(result),
                       np.load("assets/result_segment_sum.npy"),
                       atol=1e-04)
