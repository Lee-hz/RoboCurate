"""Long-context causality, weak-label boundaries and explanation semantics."""
import copy,hashlib,importlib.util
from pathlib import Path
import numpy as np
import pytest
torch=pytest.importorskip('torch')
from warp_progress.stages_v3 import MultiScaleStageNet,MotionStageNet,inference_v3,load_stage_v3
from test_core import real_library


@pytest.mark.parametrize('model_type,architecture',[(MultiScaleStageNet,'multiscale'),(MotionStageNet,'motion')])
def test_multiscale_causal_roundtrip_missing_inputs(tmp_path,model_type,architecture):
    torch.set_num_threads(1);torch.manual_seed(8)
    model=model_type().eval();rng=np.random.default_rng(11)
    x=rng.normal(size=(40,2,384)).astype(np.float32);q=rng.normal(size=(40,41)).astype(np.float32)
    cv=np.ones((40,2),bool);qv=np.ones(40,bool)
    cv[3]=False;x[3]=np.nan;qv[6]=False;q[6]=np.nan
    priors=[.2,.3,.3,.2,0.]
    a=inference_v3([model],x,cv,q,qv,priors,temperature=.6,review_guard=True)
    x[25:]*=-2;q[25:]*=3
    b=inference_v3([model],x,cv,q,qv,priors,temperature=.6,review_guard=True)
    np.testing.assert_allclose(a['probability'][:25],b['probability'][:25],equal_nan=True)
    np.testing.assert_array_equal(a['review_reasons'][:25],b['review_reasons'][:25])
    assert a['stage'][3]==-1 and a['review_reasons'][3]&8
    assert a['review_reasons'][6]&4
    p=tmp_path/'model.pt'
    torch.save(dict(kind='stage_progress',version=3,config=dict(model.config,architecture=architecture),states=[model.state_dict()]),p)
    models,_=load_stage_v3(p,hashlib.sha256(p.read_bytes()).hexdigest())
    c=inference_v3(models,x,cv,q,qv,priors,temperature=.6,review_guard=True)
    np.testing.assert_allclose(b['probability'],c['probability'],equal_nan=True)
    with pytest.raises(ValueError,match='校验失败'):load_stage_v3(p,'0'*64)


def test_motion_differences_do_not_use_invalid_endpoints():
    torch.set_num_threads(1);torch.manual_seed(13);model=MotionStageNet().eval()
    rng=np.random.default_rng(14);x=rng.normal(size=(12,2,384)).astype(np.float32);q=rng.normal(size=(12,41)).astype(np.float32)
    cv=np.ones((12,2),bool);qv=np.ones(12,bool);cv[4,0]=False;qv[6]=False
    x[4,0]=np.nan;q[6]=np.nan;prior=[.2,.3,.3,.2,0.]
    a=inference_v3([model],x,cv,q,qv,prior)
    x[4,0]=1e6;q[6]=-1e6
    b=inference_v3([model],x,cv,q,qv,prior)
    np.testing.assert_allclose(a['probability'],b['probability'])


def test_boundary_warning_uses_only_observed_changes(monkeypatch):
    stage=np.array([0,0,1,1,1,-1,3]);valid=stage>=0
    result=dict(stage=stage,valid=valid,confidence=np.where(valid,.99,np.nan),
        disagreement=np.zeros(7,bool),degraded=~valid,review=~valid)
    monkeypatch.setattr('warp_progress.stages_v3.infer_fusion',lambda *a,**k:copy.deepcopy(result))
    args=([],np.zeros((7,2,384)),np.ones((7,2),bool),np.zeros((7,41)),np.ones(7,bool),[.2,.3,.3,.2,0.])
    a=inference_v3(*args)
    assert a['boundary_review'].tolist()==[False,False,True,True,False,False,False]
    assert a['review_reasons'][2]==16
    result['stage'][4]=2
    b=inference_v3(*args)
    np.testing.assert_array_equal(a['review_reasons'][:4],b['review_reasons'][:4])
    c=inference_v3(*args,boundary_review=False)
    assert not c['boundary_review'].any() and c['review'].sum()==1


def test_review_guard_keeps_raw_uncertainty_without_changing_predictions(monkeypatch):
    calibrated=dict(stage=np.array([0,1,2]),valid=np.ones(3,bool),confidence=np.array([.95,.7,.96]),
        disagreement=np.zeros(3,bool),degraded=np.zeros(3,bool),review=np.array([False,True,False]),
        probability=np.array([[.95,.05,0],[.1,.7,.2],[0,.04,.96]]),progress=np.array([.1,.3,.5]))
    raw=copy.deepcopy(calibrated);raw['review']=np.array([True,False,False]);raw['confidence']=np.array([.72,.81,.87])
    raw['probability']*=.8;raw['stage'][:]=4;raw['progress'][:]=1
    def fake(*args):
        return copy.deepcopy(raw if args[-1]==1. else calibrated)
    monkeypatch.setattr('warp_progress.stages_v3.infer_fusion',fake)
    args=([],np.zeros((3,2,384)),np.ones((3,2),bool),np.zeros((3,41)),np.ones(3,bool),[.2,.3,.3,.2,0.])
    guarded=inference_v3(*args,temperature=.6,boundary_review=False,review_guard=True)
    assert guarded['review'].tolist()==[True,True,False]
    assert guarded['guard_review'].tolist()==[True,False,False]
    assert guarded['review_reasons'].tolist()==[32,1,0]
    for key in ['stage','probability','confidence','progress']:
        np.testing.assert_array_equal(guarded[key],calibrated[key])
    unguarded=inference_v3(*args,temperature=.6,boundary_review=False)
    np.testing.assert_array_equal(unguarded['review'],calibrated['review'])
    assert not unguarded['guard_review'].any()




def test_v3_request_includes_measured_state_and_keeps_missing_view_review(real_library):
    import sys
    from warp_progress.features import atomic_json
    from warp_fixtures import install_profile,MODEL_ID
    lib,ref=real_library;service=lib.progress_service
    profile=install_profile(service,sys.executable)
    profile.update(kind='stage_progress',stage_version=3,cameras=['head','missing_view'])
    atomic_json(service.model_root/'profiles.json',dict(models=[profile]))
    request=service._request(ref.id,MODEL_ID)
    assert request['native_fingerprint'] and Path(request['native_path']).is_file()
    assert service.models()['models'][0]['stage_version']==3
    assert service.models()['models'][0]['supports_weights'] is False
