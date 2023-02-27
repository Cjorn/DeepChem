import pytest
try:
    from deepchem.data.dft_data import DFTEntry
    from dqc.qccalc.ks import KS
    from deepchem.utils.dftutils import KSCalc
    import torch
except ModuleNotFoundError:
    raise ModuleNotFoundError("This test requires dqc and torch")


@pytest.mark.dqc
def test_entryDM():
    e_type = 'dm'
    true_val = 'deepchem/data/tests/dftHF_output.npy'
    systems = [{
        'moldesc': 'H 0.86625 0 0; F -0.86625 0 0',
        'basis': '6-311++G(3df,3pd)'
    }]
    dm_entry_for_HF = DFTEntry.create(e_type, true_val, systems)
    assert dm_entry_for_HF.entry_type == 'dm'
    dm_HF_system0 = dm_entry_for_HF.get_systems()[0]
    mol_dqc = dm_HF_system0.get_dqc_mol(dm_entry_for_HF)
    hf_zs = torch.Tensor([1, 9])
    hf_pos = torch.DoubleTensor([[0.86625, 0.0000, 0.0000],
                                 [-0.86625, 0.0000, 0.0000]])
    assert (mol_dqc.atomzs == hf_zs).all()
    assert (hf_pos.numpy() == mol_dqc.atompos.numpy()).all()
    dm0 = dm_entry_for_HF.get_true_val()
    assert dm0.shape == (57, 57)


@pytest.mark.dqc
def test_entryAE():
    e_type = 'ae'
    true_val = '0.09194410469'
    systems = [{
        'moldesc': 'Li 1.5070 0 0; H -1.5070 0 0',
        'basis': '6-311++G(3df,3pd)'
    }, {
        'moldesc': 'Li 0 0 0',
        'basis': '6-311++G(3df,3pd)',
        'spin': 1
    }, {
        'moldesc': 'H 0 0 0',
        'basis': '6-311++G(3df,3pd)',
        'spin': 1
    }]
    ae_entry_for_LiH = DFTEntry.create(e_type, true_val, systems)
    assert ae_entry_for_LiH.entry_type == 'ae'
    assert ae_entry_for_LiH.get_true_val() == 0.09194410469

    def run(syst):
        mol_dqc = syst.get_dqc_mol(ae_entry_for_LiH)
        qc = KS(mol_dqc, xc='lda_x').run()
        return KSCalc(qc)

    qcs = [run(syst) for syst in ae_entry_for_LiH.get_systems()]
    val = torch.tensor(0.0536, dtype=torch.float64)
    calc_val = ae_entry_for_LiH.get_val(qcs)
    torch.testing.assert_close(val, calc_val, atol=1e-4, rtol=0)
