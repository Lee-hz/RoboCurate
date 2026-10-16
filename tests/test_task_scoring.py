import copy
import numpy as np
import pytest
from task_scoring import simulation_task_score, channel

def scene(mode='success'):
    n=80;target=np.tile([0.,0.,.80],(n,1));basket=np.tile([0.,2.,.85],(n,1));hand=np.zeros((n,1));flags=np.zeros((n,2))
    if mode!='idle':
        target[10:60,2]=.95;target[20:60,1]=np.linspace(0,2,40);target[60:,1]=2;hand[10:65]=1
    if mode=='drop':target[60:]=[0,1.5,.02]
    if mode=='partial_start':target[:]=[0.,2.,.8]
    if mode in ('success','partial_start'):flags[70:,0]=1
    flags[70:,1]=1
    arrays={'objects.pos':np.c_[basket,target], 'sim.flags':flags,'hand.left.cmd_q':np.zeros((n,1)),'hand.right.cmd_q':hand}
    meta=dict(profile='g1_sim_lerobot',episode=dict(instruction='Pick up chili pepper from table and place in basket'),timeline=dict(step_ns=100_000_000),channels={})
    flat=[];offset=0
    for key,value in arrays.items():
        names=['container.pos_'+a for a in 'xyz']+['target.pos_'+a for a in 'xyz'] if key=='objects.pos' else ['task_success','terminal_return'] if key=='sim.flags' else ['close']
        meta['channels'][key]=dict(offset=offset,samples=n,series=value.shape[1],names=names)
        flat.extend(value.T.ravel());offset+=value.size
    return meta,np.array(flat,dtype='<f4')

def test_idle_is_zero_even_with_clean_data():
    assert simulation_task_score(*scene('idle'))['score']==0

def test_object_transport_and_release_supported():
    r=simulation_task_score(*scene());assert 8<=r['score']<=10;assert r['evidence']['complete']

def test_success_flag_cannot_create_completion():
    m,a=scene('idle');d=m['channels']['sim.flags'];a[d['offset']:d['offset']+d['samples']]=1
    r=simulation_task_score(m,a);assert r['score'] is None;assert r['source_conflict']

def test_initially_in_basket_does_not_earn_full_episode_score():
    r=simulation_task_score(*scene('partial_start'));assert r['state']=='incomplete_start';assert r['score'] is None

def test_drop_regresses_and_cannot_preserve_peak_score():
    r=simulation_task_score(*scene('drop'));assert r['score']<2;assert r['curve']['progress'][-1]<max(r['curve']['progress'])

def test_coordinate_translation_does_not_change_score():
    m,a=scene();original=simulation_task_score(m,a);d=m['channels']['objects.pos'];v=channel(m,a,'objects.pos');v+=np.tile([3.,-4.,2.],2);a[d['offset']:d['offset']+v.size]=v.T.ravel()
    assert simulation_task_score(m,a)['score']==original['score']

def test_missing_or_nonfinite_evidence_never_passes():
    m,a=scene();del m['channels']['objects.pos'];assert simulation_task_score(m,a)['score'] is None
    m,a=scene();a[10]=np.nan;assert simulation_task_score(m,a)['score'] is None

def test_wrong_task_and_real_video_are_not_simulator_scored():
    m,a=scene();m['episode']['instruction']='walk forward';assert simulation_task_score(m,a)['score'] is None
    m,a=scene();m['profile']='real';assert simulation_task_score(m,a)['score'] is None

def test_held_object_is_not_completed_placement():
    m,a=scene();d=m['channels']['hand.right.cmd_q'];a[d['offset']:d['offset']+d['samples']]=1
    r=simulation_task_score(m,a);assert r['score'] is None;assert not r['evidence']['complete']

def test_corrupt_channel_bounds_are_rejected():
    m,a=scene();m['channels']['objects.pos']['offset']=len(a)
    assert simulation_task_score(m,a)['score'] is None
