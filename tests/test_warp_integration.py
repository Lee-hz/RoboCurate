import json
import sys
from pathlib import Path
import time
import zipfile
import numpy as np
import pytest
from test_core import real_library
from warp_fixtures import install_profile,install_score,MODEL_ID
from warp_progress.features import atomic_json
from progress_service import validate_policy,ProgressService
from exporter import build_bundle,preflight
from dataset_reader import RobotDataset


def test_model_config_and_source_changes_invalidate_scores(real_library,monkeypatch):
    lib,ref=real_library;s=lib.progress_service
    profile=install_profile(s,sys.executable);original=install_score(s,ref.id)
    assert s.current(ref.id,MODEL_ID)['state']=='ready'
    profile['crop']='center';atomic_json(s.model_root/'profiles.json',dict(models=[profile]))
    assert s.current(ref.id,MODEL_ID)['state']=='absent'
    with pytest.raises(ValueError,match='有效评分'):s.for_export(ref.id,dict(model_id=MODEL_ID))
    profile['crop']='squash';atomic_json(s.model_root/'profiles.json',dict(models=[profile]))
    assert s.current(ref.id,MODEL_ID)['result']['signature']==original['signature']
    fingerprint=lib.fingerprint(ref)
    monkeypatch.setattr(lib,'fingerprint',lambda _:dict(**{**fingerprint,'size':fingerprint['size']+1}))
    assert s.current(ref.id,MODEL_ID)['state']=='absent'


def test_job_dedup_cancel_and_restart_recovery(real_library,monkeypatch):
    lib,ref=real_library;s=lib.progress_service
    install_profile(s,sys.executable)
    queued=[]
    monkeypatch.setattr(s.pool,'submit',lambda fn,job_id:queued.append(job_id))
    first=s.start(ref.id,MODEL_ID);second=s.start(ref.id,MODEL_ID)
    assert first['job']['id']==second['job']['id'] and len(queued)==1
    assert 'request' not in first['job']
    assert s.cancel(first['job']['id'])['state']=='cancelled'
    new=s.start(ref.id,MODEL_ID)
    assert new['job']['id']!=first['job']['id']
    s.close()
    job=s.job(new['job']['id']);job['state']='running'
    atomic_json(s.jobs_root/(job['id']+'.json'),job)
    recovered=ProgressService(lib)
    try:assert recovered.current(ref.id,MODEL_ID)['state']=='interrupted'
    finally:recovered.close()


@pytest.mark.parametrize('policy',[
    dict(model_id='../bad'),dict(model_id='x',horizon=True),dict(model_id='x',horizon=1.5),
    dict(model_id='x',threshold=float('nan')),dict(model_id='x',mode='unknown'),dict(model_id='x',extra=True)])
def test_invalid_export_policies(policy):
    with pytest.raises(ValueError):validate_policy(policy)


def test_weighted_export_reader_roundtrip_and_original_masks(real_library,tmp_path,monkeypatch):
    lib,ref=real_library;s=lib.progress_service
    install_profile(s,sys.executable);install_score(s,ref.id)
    policy=dict(model_id=MODEL_ID,horizon=10,threshold=1.,mode='continuous')
    options=dict(kind='dataset',fps=30,validation_ratio=0,seed=42,progress=policy)
    assert not preflight(lib,[lib.record(ref)],options)['ready']  # scores cannot grant approval
    patch=lib.validate_review(ref.id,dict(revision=0,grade='B',instruction='自动化验收样例，不代表人工任务确认',
                                       segments=[dict(start=2,end=4,label='测试一'),dict(start=5,end=7,label='测试二')]))
    lib.store.save_many([(ref.id,patch)])
    assert not preflight(lib,[lib.record(ref)],options)['ready']
    # Test-only admission fixture isolates the historical weighted export path.
    monkeypatch.setattr(lib.task_audit,'curation',lambda:dict(episodes={ref.id:dict(grade='B',score=5,reason='test fixture')}))
    record=lib.record(ref);report=preflight(lib,[record],options)
    assert report['ready'] and report['records'][0]['progress']['retained_anchors']>0
    job=dict(id='export_warp_fixture',state='running')
    bundle=build_bundle(lib,[record],options,lib.export_root,job)
    with zipfile.ZipFile(lib.export_root/bundle['file']) as z:z.extractall(tmp_path/'dataset')
    root=tmp_path/'dataset';manifest=json.loads((root/'manifest.json').read_text())
    assert manifest['episodes'][0]['progress']['validation_status']=='test_fixture'
    retained=0
    for clip in manifest['episodes'][0]['clips']:
        with np.load(root/clip['path']/'samples.npz') as a:
            assert len(a['warp.weight'])==len(a['valid'])==60
            assert not a['warp.weight'][-9:].any()
            assert (a['warp.valid']<=a['valid']).all()
            assert (a['warp.weight'][~a['warp.eligible']]==0).all()
            starts=np.flatnonzero(a['warp.weight']>0)
            assert np.allclose(a['warp.weight'][starts],a['warp.velocity'][starts+9])
            retained+=len(starts)
            assert clip['progress']['retained_anchors']==len(starts)
    ds=RobotDataset(root,split='all',sequence_length=10,curation='warp')
    assert len(ds)==retained
    assert len(RobotDataset(root,split='all',sequence_length=10))>=len(ds)
    sample=ds[0]
    assert sample['sample_weight']>1 and sample['action'].shape==(10,41)
    with pytest.raises(ValueError,match='horizon'):RobotDataset(root,curation='warp',sequence_length=1)


def test_unknown_job_and_model_paths_are_rejected(real_library):
    lib,ref=real_library;s=lib.progress_service
    with pytest.raises(ValueError):s.job('../models/profiles')
    with pytest.raises(ValueError):s.profile('missing')
    p=install_profile(s,sys.executable);p['checkpoint']='../../reviews.sqlite3'
    atomic_json(s.model_root/'profiles.json',dict(models=[p]))
    with pytest.raises(ValueError,match='模型路径'):s.profile(MODEL_ID)


def test_second_reader_does_not_interrupt_active_jobs(real_library,monkeypatch):
    lib,ref=real_library;first=lib.progress_service
    install_profile(first,sys.executable)
    monkeypatch.setattr(first.pool,'submit',lambda *args:None)
    job=first.start(ref.id,MODEL_ID)['job']
    second=ProgressService(lib)
    try:
        assert not second.owns_jobs
        assert first.job(job['id'])['state']=='queued'
        with pytest.raises(ValueError,match='另一个'):second.start(ref.id,MODEL_ID)
    finally:
        second.close();first.close()
