"""Causality, inherited v3 behavior and uncertainty-aware auxiliary supervision."""
import hashlib,importlib.util
from pathlib import Path
import numpy as np
import pytest
torch=pytest.importorskip('torch')
from warp_progress.stages_v3 import MotionStageNet
from warp_progress.stages_v4 import RefinedStageNet,inference_v4,load_stage_v4,cross_recording_contrastive,boundary_bag_loss,segment_cdf_loss
from test_core import real_library




def test_shared_initialization_and_default_forward_preserve_v3():
    torch.set_num_threads(1);torch.manual_seed(42);old=MotionStageNet().eval();state=torch.random.get_rng_state()
    torch.manual_seed(42);new=RefinedStageNet(contrastive=True,boundary=True).eval()
    assert torch.equal(state,torch.random.get_rng_state())
    for k,v in old.state_dict().items():assert torch.equal(v,new.state_dict()[k])
    x=torch.randn(4,8,2,384);cv=torch.ones(4,8,2,dtype=torch.bool);q=torch.randn(4,8,41);qv=torch.ones(4,8,dtype=torch.bool)
    for a,b in zip(old(x,cv,q,qv),new(x,cv,q,qv)):torch.testing.assert_close(a,b,rtol=0,atol=0)


def test_proxy_progress_gradients_cannot_change_stage_encoder_when_detached():
    torch.set_num_threads(1);torch.manual_seed(19)
    m=RefinedStageNet(detach_progress=True)
    inputs=(torch.randn(6,8,2,384),torch.ones(6,8,2,dtype=torch.bool),torch.randn(6,8,41),torch.ones(6,8,dtype=torch.bool))
    _,within=m(*inputs);within.mean().backward()
    assert all(p.grad is None for n,p in m.named_parameters() if not n.startswith('within.'))
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in m.within.parameters())
    m.zero_grad(set_to_none=True);logits,_=m(*inputs)
    torch.nn.functional.cross_entropy(logits,torch.tensor([0,1,2,3,4,0])).backward()
    assert m.fusion[0].weight.grad is not None and m.fusion[0].weight.grad.abs().sum()>0


def test_v4_causality_missing_inputs_checkpoint_and_training_gradients(tmp_path):
    torch.set_num_threads(1);torch.manual_seed(7);m=RefinedStageNet(contrastive=True,boundary=True).eval()
    rng=np.random.default_rng(8);x=rng.normal(size=(24,2,384)).astype('float32');q=rng.normal(size=(24,41)).astype('float32')
    cv=np.ones((24,2),bool);qv=np.ones(24,bool);cv[4]=False;x[4]=np.nan;qv[6]=False;q[6]=np.nan;prior=[.2,.3,.3,.2,0.]
    a=inference_v4([m],x,cv,q,qv,prior,.6,True)
    assert a['stage'][4]==-1 and np.isnan(a['boundary_probability'][4]) and a['review'][6]
    x[16:]*=-3;q[16:]*=2;b=inference_v4([m],x,cv,q,qv,prior,.6,True)
    for key in ['probability','review','review_reasons','boundary_probability']:
        np.testing.assert_allclose(a[key][:16],b[key][:16],equal_nan=True)
    path=tmp_path/'m.pt';torch.save(dict(kind='stage_progress',version=4,config=m.config,states=[m.state_dict()]),path)
    loaded,_=load_stage_v4(path,hashlib.sha256(path.read_bytes()).hexdigest())
    c=inference_v4(loaded,x,cv,q,qv,prior,.6,True)
    np.testing.assert_allclose(b['probability'],c['probability'],equal_nan=True)
    with pytest.raises(ValueError,match='校验失败'):load_stage_v4(path,'0'*64)
    m.train();logits,within,z,bound=m(torch.randn(8,8,2,384),torch.ones(8,8,2,dtype=torch.bool),torch.randn(8,8,41),torch.ones(8,8,dtype=torch.bool),True)
    labels=torch.tensor([0,1,2,3,0,1,2,3]);recordings=torch.tensor([1]*4+[2]*4)
    loss=torch.nn.functional.cross_entropy(logits,labels)+.05*cross_recording_contrastive(z,labels,recordings)+.1*boundary_bag_loss([bound[:3]],bound[3:])+.5*segment_cdf_loss(logits.softmax(-1)[:,0])+within.mean()
    loss.backward();assert torch.isfinite(loss) and all(torch.isfinite(p.grad).all() for p in m.parameters() if p.grad is not None)


def test_contrastive_pairs_and_interval_loss_semantics():
    z=torch.tensor([[1.,0],[0,1],[1,0],[0,1]],requires_grad=True);labels=torch.tensor([0,1,0,1]);ep=torch.tensor([1,1,2,2])
    good=cross_recording_contrastive(z,labels,ep)
    bad=cross_recording_contrastive(z[[0,1,3,2]],labels,ep)
    assert good<bad
    assert cross_recording_contrastive(z,labels,torch.ones(4,dtype=torch.long))==0
    assert boundary_bag_loss([torch.tensor([-3.,3.,-3.])],torch.tensor([-3.]))<boundary_bag_loss([torch.tensor([-3.,-3.,-3.])],torch.tensor([-3.]))
    assert boundary_bag_loss([torch.tensor([-3.,3.,-3.])],torch.tensor([-3.]))<boundary_bag_loss([torch.tensor([-3.,3.,-3.])],torch.tensor([3.]))
    assert segment_cdf_loss(torch.ones(6))<1e-12
    assert segment_cdf_loss(torch.tensor([.1,.1,.1,.1,.1,.9]))>0






def test_v4_service_identity_includes_native_state_without_torch_server_dependency(real_library):
    import sys
    from warp_progress.features import atomic_json
    from warp_fixtures import install_profile,MODEL_ID
    lib,ref=real_library;service=lib.progress_service;profile=install_profile(service,sys.executable)
    profile.update(kind='stage_progress',stage_version=4,cameras=['head','right_wrist'])
    atomic_json(service.model_root/'profiles.json',dict(models=[profile]))
    request=service._request(ref.id,MODEL_ID)
    assert request['native_fingerprint'] and Path(request['native_path']).is_file()
    assert not service.models()['models'][0]['supports_weights']
