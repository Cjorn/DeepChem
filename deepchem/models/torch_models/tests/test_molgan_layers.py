import pytest

try:
    import torch
    # import torch.nn as nn
    import torch.nn.functional as F
    import numpy as np
    # , MolGANMultiConvolutionLayer, MolGANAggregationLayer, MolGANEncoderLayer
    has_torch = True
except ModuleNotFoundError:
    has_torch = False
    pass


@pytest.mark.torch
def test_graph_convolution_layer():
    from deepchem.models.torch_models.layers import MolGANConvolutionLayer
    vertices = 9
    nodes = 5
    edges = 5
    units = 128

    layer = MolGANConvolutionLayer(units=units, edges=edges, nodes=nodes)
    adjacency_tensor = torch.randn((1, vertices, vertices, edges))
    node_tensor = torch.randn((1, vertices, nodes))
    output = layer([adjacency_tensor, node_tensor])
    output_tf = [
        (1, 9, 9, 5), (1, 9, 5), (1, 9, 128)
    ]  # None has been converted to 1 as batch size is taken as 1 in torch

    # Testing Shapes
    assert output[0].shape == output_tf[0]  # adjacency_tensor
    assert output[1].shape == output_tf[1]  # node_tensor
    assert output[2].shape == output_tf[2]  # output of the layer

    assert output[0].shape == torch.Size([1, vertices, vertices,
                                          edges])  # adjacency_tensor
    assert output[1].shape == torch.Size([1, vertices, nodes])  # node_tensor
    assert output[2].shape == torch.Size([1, vertices,
                                          units])  # output of the layer

    # Testing values
    assert layer.units == units
    assert layer.activation == F.tanh
    assert layer.edges == 5
    assert layer.dropout_rate == 0.0

@pytest.mark.torch
def test_graph_convolution_layer_values():
    from deepchem.models.torch_models.layers import MolGANConvolutionLayer
    vertices = 9
    nodes = 5
    edges = 5
    units = 128

    torch.manual_seed(21)
    layer = MolGANConvolutionLayer(units=units, edges=edges, nodes=nodes)
    tf_weights = np.load(
        'deepchem/models/tests/assets/molgan_conv_layer_weights.npy',
        allow_pickle=True).item()
    with torch.no_grad():
        for idx, dense in enumerate(layer.dense1):
            print(idx, dense)
            weight_name = f'layer1/dense_{idx+4}/kernel:0'
            bias_name = f'layer1/dense_{idx+4}/bias:0'
            dense.weight.data = torch.from_numpy(
                np.transpose(tf_weights[weight_name]))
            dense.bias.data = torch.from_numpy(tf_weights[bias_name])

    layer.dense2.weight.data = torch.from_numpy(
        np.transpose(tf_weights['layer1/dense_8/kernel:0']))
    layer.dense2.bias.data = torch.from_numpy(
        tf_weights['layer1/dense_8/bias:0'])
    adjacency_tensor = torch.randn((1, vertices, vertices, edges))
    node_tensor = torch.randn((1, vertices, nodes))
    output = layer([adjacency_tensor, node_tensor])

    adjacency_tensor = torch.from_numpy(
        np.load('deepchem/models/tests/assets/molgan_adj_tensor.npy').astype(
            np.float32))
    node_tensor = torch.from_numpy(
        np.load('deepchem/models/tests/assets/molgan_nod_tensor.npy').astype(
            np.float32))
    output = layer([adjacency_tensor, node_tensor])
    output_tensor = torch.from_numpy(
        np.load('deepchem/models/tests/assets/molgan_conv_layer_op.npy').astype(
            np.float32))

    # Testing Values
    assert torch.allclose(output[0], adjacency_tensor, atol=1e-06)
    assert torch.allclose(output[1], node_tensor, atol=1e-06)
    assert torch.allclose(output[2], output_tensor, atol=1e-04)