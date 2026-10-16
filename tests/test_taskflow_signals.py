import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest

from taskflow.signals import StateEvidence,align_measured,motion_runs,POLICY
from taskflow.media import Media
from taskflow import contracts


def fixture(tmp_path,*,only_commands=False,gap=False,invalid_order=False,unknown_unit=False):
    t0=1_789_000_000_000_000_000
    times=t0+np.arange(0,5,.02).__mul__(1e9).round().astype(np.int64)
    t=(times-t0)/1e9
    closure=np.clip((t-1)*2,0,1)-np.clip((t-3)*2,0,1)
    values=np.zeros((len(t),6));values[:,2:]=closure[:,None]
    values[:,1]=.8  # Thumb auxiliary motion must not determine four-finger closure.
    if gap:values[(t>2)&(t<2.5)]=np.nan
    if invalid_order:times[20]=times[19]
    key='hand.right.cmd_q' if only_commands else 'hand.right.state_q'
    np.savez(tmp_path/'native.npz',**{key+'.t':times,key+'.v':values,'ref.root_pos.t':times,'ref.root_pos.v':np.full((len(t),3),99.),'sim.flags.t':times,'sim.flags.v':np.ones((len(t),7))})
    meta=dict(timeline=dict(t0_ns=t0),source=dict(size_bytes=10,mtime_ns=123),joints=dict(names=[]),channels={key:dict(names=['thumb','thumb_aux','index','middle','ring','pinky'],unit='unknown' if unknown_unit else '0=open 1=closed')})
    (tmp_path/'meta.json').write_text(json.dumps(meta))
    lib=SimpleNamespace(ref=lambda _:object(),cache_dir=lambda _:tmp_path,fingerprint=lambda _:dict(size=10,mtime_ns=123))
    asset=dict(duration_s=5,source=dict(kind='recording',id='ep',snapshot=False))
    return StateEvidence(lib,asset)


def test_causal_alignment_never_reads_future_or_fills_long_holes():
    t=np.array([100,200,1000],dtype=np.int64);v=np.array([[1.],[2.],[9.]])
    out=align_measured(t,v,np.array([50,100,150,200,400,900,1000]),150)
    assert np.isnan(out[[0,4,5]]).all()
    assert out[[1,2,3,6],0].tolist()==[1,1,2,9]
    with pytest.raises(ValueError):align_measured(np.array([100,100]),v[:2],t,150)


def test_feedback_events_do_not_read_commands_reference_positions_or_success_flags(tmp_path):
    state=fixture(tmp_path)
    assert state.available
    kinds=[e['kind'] for e in state.events]
    assert kinds==['hand_closing','hand_opening']
    assert 1<=state.events[0]['start_s']<1.5 and 3<=state.events[1]['start_s']<3.5
    payload=json.dumps(state.for_model(0,5),ensure_ascii=False)
    assert 'ref.root_pos' not in payload and 'sim.flags' not in payload and '99.0' not in payload
    assert len(state.closing_barriers())==1
    assert len(state.key_times(0,5,8))<=8
    assert state.key_times(0,5,8)[0]==0 and state.key_times(0,5,8)[-1]==5


def test_commands_only_and_bad_units_do_not_become_measured_hand_evidence(tmp_path):
    assert not fixture(tmp_path,only_commands=True).available
    assert not fixture(tmp_path,unknown_unit=True).available
    assert not fixture(tmp_path,invalid_order=True).available


def test_state_gaps_and_changed_source_are_exposed(tmp_path):
    state=fixture(tmp_path,gap=True)
    assert state.summary(1.8,2.7)['facts'][0]['coverage']<1
    state.unchanged()
    with (tmp_path/'native.npz').open('ab') as stream:stream.write(b'changed')
    with pytest.raises(ValueError,match='已变化'):state.unchanged()


def test_snapshot_sim_joint_directions_are_not_labeled_open_or_closed(tmp_path):
    ep='a'*12;folder=tmp_path/'episodes'/ep;folder.mkdir(parents=True)
    n=100;v=np.r_[np.zeros(20),np.linspace(0,.8,30),np.full(20,.8),np.linspace(.8,0,30)].astype('<f4')
    v.tofile(folder/'series.bin')
    meta=dict(timeline=dict(t0_ns=0,samples=n,step_ns=50_000_000),channels={'hand.right.state_q':dict(names=['right_gripper_joint'],unit='sim joint',series=1,samples=n,offset=0)})
    (folder/'meta.json').write_text(json.dumps(meta))
    lib=SimpleNamespace(task_audit=SimpleNamespace(root=tmp_path))
    state=StateEvidence(lib,dict(duration_s=5,source=dict(kind='recording',id=ep,snapshot=True)))
    assert state.available and state.storage=='resampled_snapshot'
    assert all(e['kind'].startswith('sim_hand') for e in state.events)
    assert not state.closing_barriers()


def test_event_detector_does_not_bridge_missing_values():
    t=np.arange(10)*.05;speed=np.array([1,1,1,np.nan,np.nan,1,1,1,1,1.])
    runs=motion_runs(t,speed,.5,.2)
    assert len(runs)==2 and runs[0][1]<=3 and runs[1][0]>=5


def task():return contracts.task_spec(dict(task_name='测试',task_goal='物体留在目标处',stages=[dict(id='place',name='放置',goal='物体在目标中',success_criteria=['可见结果在目标内'])]))


def proposal(status='completed',observability='direct',frame='late'):
    return dict(stage_id='place',start_s=1,end_s=2,reason='检查结果',evidence_frame_ids=[frame],criteria_results=[dict(criterion_index=0,status=status,observability=observability,reason='解释',evidence_frame_ids=[frame])])


def test_explicit_later_observation_allowed_but_crossing_next_closing_abstains():
    frames=[dict(id='late',time_s=6.)]
    out=contracts.segments([proposal()],task(),1,2,frames,True,evidence_window=(0,8),barriers=[7],require_observability=True)
    assert out[0]['completion']=='completed'
    out=contracts.segments([proposal()],task(),1,2,frames,True,evidence_window=(0,8),barriers=[5],require_observability=True)
    assert out[0]['completion']=='uncertain'
    assert out[0]['criteria_results'][0]['rejected_evidence_frame_ids']==['late']


def test_limited_visibility_never_passes_even_when_model_claims_success():
    row=proposal(observability='limited',frame='now');frames=[dict(id='now',time_s=1.5)]
    out=contracts.segments([row],task(),1,2,frames,True,require_observability=True)
    assert out[0]['completion']=='uncertain'
    assert out[0]['criteria_results'][0]['model_status']=='completed'
    with pytest.raises(ValueError,match='未提供'):
        contracts.segments([proposal(frame='reference')],task(),1,2,frames,True,evidence_window=(0,8),require_observability=True)


def test_guided_camera_budget_keeps_timestamps_and_does_not_exceed_limit(tmp_path,monkeypatch):
    state=fixture(tmp_path);media=Media(SimpleNamespace(),tmp_path/'media')
    monkeypatch.setattr(media,'camera_names',lambda a:['head','right_wrist','left_wrist'])
    monkeypatch.setattr(media,'frame',lambda a,t,camera:dict(id=f'{camera}-{t}',time_s=t,camera=camera))
    asset=dict(duration_s=5,source=dict(camera='head',timing='mcap_log_time'))
    frames,coverage=media.sample_guided(asset,state,0,5,budget=16,core=(1,3))
    assert len(frames)<=16 and coverage['requested']<=16
    assert set(f['camera'] for f in frames)=={'head','right_wrist','left_wrist'}
    assert all(0<=f['time_s']<=5 for f in frames)
    assert coverage['strategy']=='state_guided_multiview'


def test_video_without_state_has_explicit_uniform_fallback(tmp_path,monkeypatch):
    media=Media(SimpleNamespace(),tmp_path);state=StateEvidence(SimpleNamespace(),dict(duration_s=5,source=dict(kind='video')))
    monkeypatch.setattr(media,'sample',lambda *a,**kw:([{'id':'a'},{'id':'b'}],{}))
    _,coverage=media.sample_guided(dict(duration_s=5),state)
    assert coverage['strategy']=='uniform_no_state' and coverage['state_reason']


def test_fractional_episode_endpoint_is_never_rounded_outside_source(tmp_path):
    state=fixture(tmp_path)
    end=4.842835583
    times=state.key_times(.123456789,end,12,core=(1,3))
    assert min(times)>=.123456789 and max(times)<=end and times[-1]==end


def test_tiny_unobserved_leading_and_trailing_gaps_are_not_fake_action_segments():
    rows=[dict(stage_id=None,start_s=0,end_s=.013,reason='无画面'),dict(stage_id='place',start_s=.013,end_s=2,reason='动作',evidence_frame_ids=['f']),dict(stage_id=None,start_s=2,end_s=2.02,reason='末尾无画面')]
    parts=contracts.segments(rows,task(),0,2.02,[dict(id='f',time_s=1)],True)
    assert len(parts)==3 and parts[0]['completion']==parts[-1]['completion']=='uncertain'
    rows[0]['stage_id']='place'
    with pytest.raises(ValueError,match='不足'):contracts.segments(rows,task(),0,2.02,[dict(id='f',time_s=1)])


def test_millisecond_endpoint_rounding_is_logged_but_real_overflow_is_rejected():
    row=proposal(frame='f');row.update(start_s=1,end_s=2.0004)
    out=contracts.segments([row],task(),1,2,[dict(id='f',time_s=1.5)],True)
    assert out[0]['end_s']==2 and out[0]['boundary_rounding_correction']['original_end_s']==2.0004
    row['end_s']=2.02
    with pytest.raises(ValueError):contracts.segments([row],task(),1,2,[dict(id='f',time_s=1.5)],True)


def test_one_missing_joint_does_not_erase_other_measured_columns():
    from taskflow.signals import smooth,velocity
    t=np.arange(8,dtype=np.int64)*50_000_000
    v=np.column_stack([np.arange(8.),np.full(8,np.nan)])
    out=align_measured(t,v,t,100_000_000)
    assert np.isfinite(out[:,0]).all() and np.isnan(out[:,1]).all()
    filtered=smooth(out);speed=velocity(filtered)
    assert np.isfinite(speed[-1,0]) and np.isnan(speed[:,1]).all()


def test_model_narrative_clips_continuing_events_to_the_requested_window(tmp_path):
    state=fixture(tmp_path);event=state.events[0]
    start,end=event['start_s']+.05,event['end_s']-.05
    summary=state.for_model(start,end)
    assert summary['events']
    assert all(start<=e['start_s']<=e['end_s']<=end for e in summary['events'])
    assert summary['events'][0]['ongoing_at_window_start']
    assert summary['events'][0]['continues_after_window']


def test_playback_preserves_missing_values_and_does_not_export_smoothed_or_command_channels():
    from taskflow.signals import StateEvidence
    evidence=StateEvidence.__new__(StateEvidence)
    evidence.times=np.array([0.,.05,.1]);evidence.reason='';evidence.storage='native_feedback';evidence.fingerprint='fingerprint';evidence.warnings=[]
    evidence.channels=[dict(key='state.q',names=['joint'],unit='rad')]
    evidence.measured={'state.q':np.array([[1.],[np.nan],[3.]])}
    evidence.values={'state.q':np.array([[10.],[20.],[30.]])}
    data=evidence.playback()
    assert data['channels'][0]['values']==[[1.],[None],[3.]]
    assert data['times_s']==[0.,.05,.1] and data['rate_hz']==20
