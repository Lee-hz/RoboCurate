import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pytest

from exporter import align, build_bundle, preflight
from storage import Store, Conflict
from studio import StudioLibrary
from dataset_reader import RobotDataset
from frames import FrameStore
from mcap.reader import make_reader
from server import _jpeg_payload


def test_causal_actions_and_invalid_gaps():
    t=np.array([100,200,500],dtype=np.int64)
    v=np.array([[1],[2],[5]],dtype=np.float32)
    g=np.array([0,100,150,200,400,500,501],dtype=np.int64)
    out,valid=align(t,v,g,hold=True,max_gap_ns=100)
    assert valid.tolist()==[False,True,True,True,False,True,False]
    assert out[2,0]==1  # future command at 200 is never used at 150


def test_state_interpolation_does_not_cross_dropouts():
    base=1_789_033_864_925_712_875
    t=np.array([base,base+20,base+1000],dtype=np.int64)
    v=np.array([[0],[2],[100]],dtype=np.float32)
    out,valid=align(t,v,t[:1]+np.array([0,10,20,500,1000]),max_gap_ns=100)
    assert valid.tolist()==[True,True,True,False,True]
    assert out[1,0]==1  # nanosecond precision, independent of epoch magnitude


def test_duplicate_and_nonfinite_exact_sample():
    out,valid=align(np.array([10,10,20]),np.array([[1.],[2.],[np.nan]]),np.array([10,15,20]))
    assert valid.tolist()==[True,False,False]
    assert out[0,0]==2


def test_quaternion_antipodes():
    out,valid=align(np.array([0,10]),np.array([[1.,0,0,0],[-1.,0,0,0]]),np.array([5]),quaternion=True)
    assert valid[0] and np.allclose(out,[[1,0,0,0]])


def test_transactional_revision_conflict(tmp_path):
    s=Store(tmp_path/'db.sqlite')
    s.save_many([('a',dict(revision=0,grade='B'))])
    with pytest.raises(Conflict):
        s.save_many([('b',dict(revision=0,grade='C')),('a',dict(revision=0,grade='A'))])
    assert 'b' not in s.all() and s.all()['a']['grade']=='B'
    assert Store(tmp_path/'db.sqlite').all()['a']['revision']==1
    assert s.history('a')[0]['before']['grade']==''


@pytest.fixture
def real_library(tmp_path):
    app=Path(__file__).resolve().parents[1]
    source=app.parent/'2026_09_10-17_40_44/data/lenovo/v141_smoke/episode_000131/mcap/mcap_0.mcap'
    if not source.exists():pytest.skip('real recording is not present')
    lib=StudioLibrary(tmp_path/'workspace');lib.add_root(source)
    ref=lib.ref(lib.order[0]);original=app/'workspace/cache'/lib.cache_dir(ref).name
    if not (original/'native.npz').exists():pytest.skip('run QC for episode_000131 first')
    lib.cache_dir(ref).parent.mkdir(parents=True,exist_ok=True)
    lib.cache_dir(ref).symlink_to(original,target_is_directory=True)
    yield lib,ref
    lib.progress_service.close();lib.pool.shutdown();lib.export_pool.shutdown()


def test_segment_validation_and_export_guards(real_library):
    lib,ref=real_library
    with pytest.raises(ValueError,match='重叠'):
        lib.validate_review(ref.id,dict(revision=0,segments=[dict(start=1,end=3),dict(start=2,end=4)]))
    with pytest.raises(ValueError,match='至少'):
        lib.validate_review(ref.id,dict(revision=0,segments=[dict(start=-1,end=2)]))
    with pytest.raises(ValueError,match='人工等级'):
        lib.export(dict(ids=[ref.id],kind='dataset'))
    assert lib.exports()==[]  # failed preflight must not create a background job


def test_real_export_roundtrip(real_library,tmp_path):
    lib,ref=real_library
    # Synthetic admission fixture exercises export, not a claim about this recording.
    lib.task_audit.curation=lambda:dict(episodes={ref.id:dict(grade='B',score=6.25,reason='测试准入夹具')})
    before=(ref.path.stat().st_size,ref.path.stat().st_mtime_ns)
    event=lib.diagnostics(ref.id)['events'][0]
    patch=lib.validate_review(ref.id,dict(revision=0,grade='B',instruction='自动化导出验收，不代表人工任务判定',event_decisions={event['id']:'accepted'},
                                        segments=[dict(start=2,end=3,label='测试片段一'),dict(start=5,end=6,label='测试片段二')]))
    lib.store.save_many([(ref.id,patch)])
    row=lib.record(ref)
    job={'id':'export_test','state':'running'}
    result=build_bundle(lib,[row],dict(kind='dataset',fps=30,validation_ratio=.2,seed=42),lib.export_root,job)
    assert result['samples']==60 and result['valid_samples']>=54
    with zipfile.ZipFile(lib.export_root/result['file']) as z:
        manifest=json.loads(z.read('manifest.json'));ep=manifest['episodes'][0]
        assert ep['source_eligible'] is False
        assert ep['quality']['grading']['version'] == 2
        assert ep['quality']['grading']['grade'] == 'B'
        assert ep['quality']['rating']['max_score'] == 10
        assert ep['quality']['rating']['version'] == 4
        assert ep['quality']['score'] == 6.25
        assert 0 <= ep['quality']['score'] <= 10
        assert ep['quality']['score'] == ep['quality']['rating']['score']
        assert z.read('README.txt').decode().startswith('RoboCurate')
        assert len(ep['sha256'])==64 and len(ep['feature_layout']['action'])==41
        assert len(ep['clips'])==2
        assert ep['reviewed_events_with_evidence']==1 and not ep['reviewed_events_missing_evidence']
        assert ep['review']['event_evidence'][event['id']]['event']['peak_s']==event['peak_s']
        for clip in ep['clips']:
            with np.load(io.BytesIO(z.read(clip['path']+'/samples.npz')),allow_pickle=False) as data:
                assert data['action'].shape==(30,41)
                assert np.isfinite(data['action'][data['valid']]).all()
                assert np.isfinite(data['observation.state'][data['valid']]).all()
                assert np.all(data['timestamp_s']>=clip['start'])
                assert np.all(data['timestamp_s']<clip['end'])
                rows=[json.loads(s) for s in z.read(clip['path']+'/images.jsonl').splitlines()]
                for name in ['head','left_wrist','right_wrist']:
                    valid=data['valid.camera.'+name];times=data['camera.'+name+'.timestamp_ns']
                    assert np.all(times[valid]<=data['timestamp_ns'][valid])
                    for r in rows:
                        p=r['images'][name]
                        if p:assert z.read(clip['path']+'/'+p).startswith(b'\xff\xd8')
        unpacked=tmp_path/'trusted-generated-bundle'
        z.extractall(unpacked)
    ds=RobotDataset(unpacked,split='all',sequence_length=4,images=True,head_view='left')
    assert len(ds)>40
    item=ds[0]
    assert item['observation.state'].shape==(4,41)
    assert item['observation.images.head'].shape==(4,3,224,224)
    assert np.allclose(np.diff(item['timestamp_s']),1/30)
    assert before==(ref.path.stat().st_size,ref.path.stat().st_mtime_ns)


def test_corrupt_record_is_reported(tmp_path):
    p=tmp_path/'broken.mcap';p.write_bytes(b'not an MCAP')
    lib=StudioLibrary(tmp_path/'workspace');lib.add_root(p)
    record=lib.catalog()['episodes'][0]
    assert record['error'] and record['quality']['suggested_grade']=='D'
    assert record['quality']['technical']['status']=='error'
    lib.pool.shutdown();lib.export_pool.shutdown()


def test_preflight_finds_blockers_and_matches_shared_plan(real_library):
    lib,ref=real_library
    lib.task_audit.curation=lambda:dict(episodes={ref.id:dict(grade='B',score=6.25,reason='测试准入夹具')})
    report=lib.preflight(dict(ids=[ref.id],kind='dataset',fps=30))
    assert not report['ready']
    assert any('任务指令' in b for b in report['records'][0]['blockers'])
    assert report['samples']>0 and not any('没有 A / B' in b for b in report['records'][0]['blockers'])
    patch=lib.validate_review(ref.id,dict(revision=0,grade='B',instruction='隔离测试指令',segments=[dict(start=2,end=3,label='片段')]))
    lib.store.save_many([(ref.id,patch)])
    report=lib.preflight(dict(ids=[ref.id],kind='dataset',fps=30))
    assert report['ready'] and report['samples']==30 and report['aligned_samples']>=27
    assert report['records'][0]['warnings']  # original RGB-only constraint stays visible


def test_restore_adds_history_and_preserves_event_decisions(real_library):
    lib,ref=real_library
    event=lib.diagnostics(ref.id)['events'][0]['id']
    first=lib.validate_review(ref.id,dict(revision=0,grade='B',note='first',event_decisions={event:'accepted'}))
    lib.store.save_many([(ref.id,first)])
    seq=lib.store.history(ref.id)[0]['seq']
    lib.store.save_many([(ref.id,lib.validate_review(ref.id,dict(revision=1,note='second')))])
    restored=lib.restore_review(dict(ep=ref.id,revision=2,seq=seq))[ref.id]
    assert restored['revision']==3 and restored['note']=='first'
    assert restored['event_decisions'][event]=='accepted'
    assert restored['event_evidence'][event]['event']['id']==event
    assert len(lib.store.history(ref.id))==3
    with pytest.raises(Conflict):lib.restore_review(dict(ep=ref.id,revision=2,seq=seq))


def test_event_evidence_is_server_captured_not_client_supplied(real_library):
    lib,ref=real_library
    diagnostic=lib.diagnostics(ref.id);event=diagnostic['events'][0]
    body=dict(revision=0,event_decisions={event['id']:'accepted'},event_evidence={event['id']:{'event':{'value':99999}}})
    patch=lib.validate_review(ref.id,body)
    evidence=patch['event_evidence'][event['id']]
    assert evidence['event']==event and evidence['signature']==diagnostic['signature']
    assert evidence['source']['path']==str(ref.path)


def test_event_evidence_survives_rule_changes(real_library):
    lib,ref=real_library
    event=lib.diagnostics(ref.id)['events'][0]
    patch=lib.validate_review(ref.id,dict(revision=0,event_decisions={event['id']:'confirmed'}))
    original=patch['event_evidence'][event['id']]
    lib.store.save_many([(ref.id,patch)])
    lib.store.set_setting('rules',{**lib.rules(),'tracking_p99_rad':.9})
    changed=lib.validate_review(ref.id,dict(revision=1,event_decisions={event['id']:'accepted'}))
    assert changed['event_evidence'][event['id']]==original
    assert original['rules']['tracking_p99_rad']==.5


def test_missing_legacy_evidence_is_explicit(real_library):
    lib,ref=real_library
    patch=lib.validate_review(ref.id,dict(revision=0,event_decisions={'f'*20:'accepted'}))
    assert patch['event_evidence']['f'*20]['unresolved'] is True


def test_unsaved_decision_recovers_its_original_rule_snapshot(real_library):
    lib,ref=real_library
    old=lib.diagnostics(ref.id);event=old['events'][0]
    lib.store.set_setting('rules',{**lib.rules(),'tracking_p99_rad':.9})
    patch=lib.validate_review(ref.id,dict(revision=0,event_decisions={event['id']:'accepted'}))
    assert patch['event_evidence'][event['id']]['signature']==old['signature']
    assert patch['event_evidence'][event['id']]['rules']['tracking_p99_rad']==.5


def test_exact_frame_batches_match_original_mcap(real_library):
    lib,ref=real_library
    index=lib.frame_store.index(ref.id)
    for name,cam in index['cameras'].items():
        header,frames=lib.frame_store.batch(ref.id,name,10,4,index['token'])
        with ref.path.open('rb') as f:
            originals=[_jpeg_payload(m.data) for _,_,m in make_reader(f).iter_messages(topics=[cam['topic']],start_time=cam['times'][10],end_time=cam['times'][13]+1)]
        assert frames==originals and all(frame.startswith(b'\xff\xd8') for frame in frames)
        assert header['frames'][0]['time_s']==(cam['times'][10]-index['start_ns'])/1e9
    with pytest.raises(Conflict):lib.frame_store.batch(ref.id,'head',0,1,'stale-token')
    with pytest.raises(ValueError):lib.frame_store.batch(ref.id,'head',0,25,index['token'])


def test_duplicate_timestamps_and_frame_cache_bound(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import frames as module
    import struct
    path=tmp_path/'synthetic.mcap';path.write_bytes(b'fixture')
    first=b'\xff\xd8\xffone';second=b'\xff\xd8\xfftwo'
    messages=[SimpleNamespace(log_time=100,data=struct.pack('<I',len(b))+b) for b in [first,second]]
    monkeypatch.setattr(module,'make_reader',lambda f:SimpleNamespace(iter_messages=lambda **kwargs:iter((None,None,m) for m in messages)))
    lib=SimpleNamespace(ref=lambda ep:SimpleNamespace(path=path),fingerprint=lambda ref:{'size':1,'mtime_ns':2})
    store=FrameStore(lib,max_bytes=1)
    store.index=lambda ep:dict(token='1:2',start_ns=0,cameras={'head':dict(topic='/head',times=[100,100])})
    header,payloads=store.batch('fixture','head',1,1,'1:2')
    assert payloads==[second] and header['frames'][0]['index']==1
    assert store.cache_bytes<=1


def test_data_grade_d_blocks_training_even_with_manual_approval(real_library, tmp_path):
    import copy
    lib, ref = real_library
    record = copy.deepcopy(lib.record(ref))
    record['review'].update(grade='A', instruction='拿起桌上的物体并放入容器', source_fingerprint=lib.fingerprint(ref))
    record['quality']['grading'].update(grade='D', summary='必需相机通道缺失')
    options = dict(kind='dataset', fps=30)
    result = preflight(lib, [record], options)
    assert not result['ready']
    assert any('自动数据等级 D' in b for b in result['records'][0]['blockers'])
    with pytest.raises(ValueError, match='自动数据等级 D'):
        build_bundle(lib, [record], options, tmp_path, {'id':'export_rejected'})
    assert not list(tmp_path.glob('*.zip'))


@pytest.mark.parametrize('grade',['E','R','U'])
def test_unqualified_task_blocks_training_even_with_manual_approval(real_library,tmp_path,grade):
    import copy
    lib,ref=real_library
    record=copy.deepcopy(lib.record(ref))
    record['review'].update(grade='A',instruction='拿起物体放进篮子',source_fingerprint=lib.fingerprint(ref))
    record['quality']['grading'].update(method='deminf_qualified_v2',grade=grade,summary='过程不完整或准入待核实')
    options=dict(kind='dataset',fps=30)
    result=preflight(lib,[record],options)
    assert not result['ready']
    assert any('未通过任务准入' in b for b in result['records'][0]['blockers'])
    with pytest.raises(ValueError,match='未通过任务准入'):
        build_bundle(lib,[record],options,tmp_path,{'id':'export_unqualified'})
    assert not list(tmp_path.glob('*.zip'))
