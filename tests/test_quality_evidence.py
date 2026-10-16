import itertools
from pathlib import Path
import sys
import numpy as np
import pytest

from quality_evidence import fixed_spacing, raw_timing, motion_facts, value_facts, integrity_summary


def test_late_failure_is_not_hidden_by_an_early_warning():
    t=np.arange(100)/20;t[1:]+=.0002;t[70:]+=.11
    r=fixed_spacing(t,20)
    assert r['severity']=='FAIL' and r['failure_count']==1


def test_raw_and_export_clocks_use_different_tolerances():
    t=np.arange(100)*50_000_000;t[1:]+=200_000
    assert fixed_spacing(t/1e9,20)['severity']=='WARN'
    assert raw_timing(t)['period_violation_pct']==0
    offset=1_789_000_000_123_456_789
    assert raw_timing(t+offset)==raw_timing(t)


def test_unknown_does_not_become_a_clean_score():
    assert fixed_spacing([],30)['severity']=='SKIP'
    assert integrity_summary([])['score'] is None
    assert integrity_summary([dict(severity='ERROR')])['score'] is None
    partial=integrity_summary([dict(severity='PASS'),dict(severity='SKIP')])
    assert partial['state']=='incomplete' and partial['measured_checks']==1


def test_nonfinite_clock_is_not_silently_clean():
    assert fixed_spacing([0,.05,np.nan],20)['severity']=='FAIL'
    assert fixed_spacing([0,.05,.05],20)['severity']=='FAIL'


def test_motion_masks_missing_rows_and_long_gaps():
    t=np.array([0,50_000_000,1_000_000_000,1_050_000_000])
    x=np.array([[0.],[.1],[999.],[999.1]])
    r=motion_facts(t,x)
    assert r['mean_velocity']==pytest.approx(2)
    assert r['valid_velocity_s']==pytest.approx(.1) and r['gap_count']==1
    assert 'trajectory_change_p95' not in r
    x[1]=np.nan
    assert motion_facts(t,x)['valid_step_count']==1


def test_backward_clock_refuses_misleading_motion_metrics():
    t=np.array([0,100_000_000,50_000_000,75_000_000,200_000_000])
    r=motion_facts(t,np.arange(5))
    assert r['state']=='not_measured' and r['reason']=='timestamp_reversal'
    assert 'mean_velocity' not in r


def test_hold_commands_are_facts_not_failure_verdicts():
    x=np.zeros((20,6));v=value_facts(x)
    assert v['unchanged_dimensions']==list(range(6)) and v['repeated_step_pct']==100
    assert 'grade' not in v and v['advisory_only']
    m=motion_facts(np.arange(20)*50_000_000,x)
    assert m['motionless_fraction']==1 and 'final_pose_unsettled_ratio' not in m
    assert integrity_summary([dict(severity='PASS'),dict(severity='FAIL',tier='quality')])['score']==100


def test_incomplete_sample_invalidates_whole_motion_step():
    t=np.arange(5)*50_000_000;x=np.ones((5,3));x[2,1]=np.inf
    r=motion_facts(t,x)
    assert r['valid_step_count']==2 and r['non_finite_value_count']==1
