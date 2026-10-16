import json
from pathlib import Path

import numpy as np
import pytest

from sim_segments import identify


def fixture():
    t=np.arange(0,12,.01);n=len(t)
    target=np.tile([0.,0.,.8],(n,1));basket=np.tile([0.,2.,.88],(n,1));grip=np.zeros(n)
    grip[(t>=1)&(t<4)]=1;grip[(t>=7)&(t<9)]=1
    target[(t>=1.3)&(t<4),2]=1.
    target[(t>=2)&(t<4),1]=np.linspace(0,2,np.sum((t>=2)&(t<4)))
    target[t>=4]=[.25,2,.8]
    target[(t>=7.3)&(t<9)]=[0.,2.,1.]
    target[t>=9]=[0.,2.,.82]
    wrist=target+[.4,0.,.1];wrist[grip>.5]=target[grip>.5]+[.1,0.,.1]
    speed=np.zeros(n);speed[(t>=5)&(t<7)]=.2
    return t,target,basket,grip,wrist,speed,n


def test_regrasp_and_second_placement_are_distinct_segments():
    result=identify(*fixture())
    kinds=[s['stage'] for s in result['segments']]
    assert len(kinds)>5 and kinds.count(1)>=2 and kinds.count(3)>=2
    first_place=kinds.index(3)
    assert 1 in kinds[first_place+1:]
    assert [a['result'] for a in result['attempts']]==['outside','inside_candidate']
    assert result['failed_placements']==1
    events=[e for e in result['quality_events'] if e['kind']=='placement']
    assert events[0]['segment_id']!=events[1]['segment_id']
    assert any(s['quality']=='issue' for s in result['segments'])


def test_final_success_never_erases_first_failed_attempt():
    r=identify(*fixture())
    assert r['attempts'][-1]['result']=='inside_candidate'
    assert r['attempts'][0]['result']=='outside' and r['failed_placements']==1
    assert r['attempts'][0]['next_grasp_s']==pytest.approx(7.)


def test_missing_post_release_observation_stays_unknown():
    args=list(fixture());args[-1]=round(4.1/.01)
    r=identify(*args)
    assert r['attempts'][0]['result']=='unknown'


def test_release_without_lifting_is_not_counted_as_placement():
    args=list(fixture());args[1][:,2]=.8
    r=identify(*args)
    assert r['attempts']==[] and r['grasp_retry_candidates']==2


def test_real_failure_recovery_regression_if_local_demo_exists():
    p=Path('workspace/sim-demo/33dc41a9ab95.json')
    if not p.exists():pytest.skip('Local recorded simulation is not bundled')
    r=json.loads(p.read_text());attempts=r['placement_attempts']
    assert len(attempts)==2
    assert attempts[0]['release_s']==pytest.approx(18.19,abs=.03)
    assert attempts[0]['result']=='outside'
    assert attempts[1]['release_s']==pytest.approx(43.03,abs=.03)
    assert attempts[1]['result']=='inside_candidate'
    assert r['record']['demo_grade']=='C'
    assert '放置偏离' in r['record']['demo_reason']
