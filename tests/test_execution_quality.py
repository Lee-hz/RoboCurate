"""Execution decisions must not invent safety or reward fast failure."""
import copy
import json

import numpy as np
import pytest

from execution_quality import MODEL_NAMES, aggregate, apply_review, build_report
from storage import Conflict
from test_core import real_library


def report_fixture():
    result = dict(stage_names=MODEL_NAMES, signature='saved-stage', model_id='g1-stage-v3',
                  stage_segments=[dict(stage=k,start_s=k*2.,end_s=(k+1)*2.,review_fraction=0.) for k in range(5)])
    meta = dict(episode=dict(start_ns=1000000000,duration_s=10.),source=dict(path='fixture'))
    out = build_report(result,meta,{},dict(events=[]))
    out['signature']='evidence-v1'
    return out,result,meta


def decisions(report):
    return dict(signature=report['signature'],revision=1,phases={
        p['id']:dict(checks={c[0]:'pass' for c in p['checks']},boundary_confirmed=True,
                     target_s=3. if p['key']!='retreat' else None) for p in report['phases']})


def test_empty_and_missing_evidence_never_pass():
    report,_,_=report_fixture()
    out=apply_review(report,{})
    assert out['state']=='pending' and out['summary']['confirmed']==0
    assert all(m['value'] is None for p in out['phases'] for m in p['metrics'])
    assert out['automatic_execution_verdict'] is False
    assert aggregate([])=='pending'


def test_fast_failure_and_unknown_safety_cannot_be_averaged_away():
    report,_,_=report_fixture();review=decisions(report)
    assert apply_review(report,review)['state']=='passed'
    review['phases']['phase-1']['checks']['accuracy']='fail'
    out=apply_review(report,review)
    assert out['state']=='fail'
    assert out['phases'][1]['checks'][-1]['status']=='blocked'
    review['phases']['phase-1']['checks']['accuracy']='unknown'
    assert apply_review(report,review)['state']=='unknown'


def test_whole_robot_retreat_is_required_separately_from_arm():
    report,_,_=report_fixture();review=decisions(report)
    last=review['phases']['phase-4']
    last['checks']['base_clear']='pending'
    assert apply_review(report,review)['state']=='pending'
    last['checks']['base_clear']='unknown'
    assert apply_review(report,review)['state']=='unknown'
    last['checks']['base_clear']='pass';last['boundary_confirmed']=False
    assert apply_review(report,review)['state']=='pending'


def test_speed_requires_complete_boundary_and_explicit_target():
    report,_,_=report_fixture();review=decisions(report)
    p=review['phases']['phase-0']
    p['target_s']=None
    assert apply_review(report,review)['phases'][0]['state']=='pending'
    p['target_s']=1.
    assert apply_review(report,review)['phases'][0]['state']=='fail'
    p['boundary_confirmed']=False
    assert apply_review(report,review)['phases'][0]['state']=='pending'


def test_model_observation_does_not_prove_retreat_and_stale_reviews_are_ignored():
    report,result,meta=report_fixture();review=decisions(report)
    old=copy.deepcopy(report)
    report['signature']='new-evidence'
    out=apply_review(report,review)
    assert out['review_stale'] and out['state']=='pending'
    assert old['phases'][-1]['model_name']=='释放后观察'
    assert old['phases'][-1]['name']=='释放后撤离'
    result['stage_segments']=result['stage_segments'][:-1]
    partial=build_report(result,meta,{},dict(events=[]));partial['signature']='partial'
    assert apply_review(partial,{})['phases'][-1]['state']=='unknown'


def test_metrics_use_native_interval_and_events_keep_zero_duration_anomalies():
    report,result,meta=report_fixture();t0=meta['episode']['start_ns']
    t=t0+np.array([.5,1.,2.,2.5])*1e9;t=t.astype(np.int64)
    values=np.array([[0.,0.,0.],[.1,.2,0.],[7.,8.,9.],[8.,9.,10.]])
    native={'imu.rpy.t':t,'imu.rpy.v':values}
    events=[dict(id='point',start_s=1.,end_s=1.),dict(id='gap',start_s=1.5,end_s=2.5)]
    result=build_report(result,meta,native,dict(events=events))
    phase=result['phases'][0]
    assert phase['metrics'][0]['value']==pytest.approx(np.rad2deg(.1),abs=1e-4)
    assert [e['id'] for e in phase['events']]==['point','gap']
    assert phase['events'][1]['overlap_end_s']==2.
    native['imu.rpy.v'][0,0]=np.nan
    assert build_report(report_fixture()[1],meta,native,dict(events=[]))['phases'][0]['metrics'][0]['value'] is None


def test_real_review_revision_history_and_separation_from_existing_grades(real_library,monkeypatch):
    lib,ref=real_library;service=lib.execution_quality
    fixture,_,_=report_fixture()
    monkeypatch.setattr(service,'evidence',lambda ep,model:fixture)
    before=lib.store.all()
    body=dict(ep=ref.id,model_id='g1-stage-v3',signature=fixture['signature'],revision=0,phase_id='phase-4',
              decision=dict(checks=dict(arm_clear='pass',base_clear='unknown',safety='unknown'),
                            boundary_confirmed=False,note='Synthetic audit fixture: recording ends before whole-body retreat.'))
    out=service.save(body)
    assert out['state']=='unknown' and out['review']['revision']==1
    assert service.current(ref.id,'g1-stage-v3')['review']['phases']['phase-4']['origin']=='human_review'
    assert lib.store.all()==before
    with pytest.raises(Conflict):service.save(body)
    body['revision']=1;body['signature']='stale'
    with pytest.raises(Conflict):service.save(body)
    with lib.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM execution_history').fetchone()[0]==1


def test_review_rejects_claims_without_basis(real_library,monkeypatch):
    lib,ref=real_library;service=lib.execution_quality;fixture,_,_=report_fixture()
    monkeypatch.setattr(service,'evidence',lambda ep,model:fixture)
    body=dict(ep=ref.id,model_id='g1-stage-v3',signature=fixture['signature'],revision=0,phase_id='phase-0',
              decision=dict(checks=dict(safety='pass'),boundary_confirmed=True,note=''))
    with pytest.raises(ValueError,match='审核依据'):service.save(body)
    body['decision'].update(note='Synthetic fixture',target_s=3.)
    with pytest.raises(ValueError,match='目标用时的依据'):service.save(body)
    body['decision'].update(pace_basis='Test protocol',target_s=float('nan'))
    with pytest.raises(ValueError,match='目标用时'):service.save(body)
    assert service.review(ref.id+':g1-stage-v3')['revision']==0


def test_corrected_interval_recomputes_evidence_and_speed_without_changing_model(real_library,monkeypatch):
    lib,ref=real_library;service=lib.execution_quality;fixture,_,_=report_fixture()
    original=copy.deepcopy(fixture)
    monkeypatch.setattr(service,'evidence',lambda ep,model:fixture)
    body=dict(ep=ref.id,model_id='g1-stage-v3',signature=fixture['signature'],revision=0,phase_id='phase-0',
              decision=dict(checks=dict(safety='pass'),boundary_confirmed=True,note='Synthetic boundary correction test',
                            target_s=1.5,pace_basis='Synthetic test protocol',start_s=.5,end_s=1.5))
    out=service.save(body);p=out['phases'][0]
    assert p['duration_s']==1. and p['state']=='passed'
    assert p['interval_source']=='human_corrected'
    assert p['candidate_start_s']==0. and p['candidate_end_s']==2.
    assert any(m['value'] is not None for m in p['metrics'])
    assert fixture==original
    body['revision']=1;body['decision']['end_s']=100.
    with pytest.raises(ValueError,match='阶段区间'):service.save(body)
    assert service.review(ref.id+':g1-stage-v3')['revision']==1
