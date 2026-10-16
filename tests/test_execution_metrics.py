import numpy as np
import pytest

from execution_metrics import closing_events, phase_metrics, with_duration_target, longest_run


def native_imu(angle=0.,duration=1.,step=.01):
    t0=1_789_033_864_925_712_875
    seconds=np.arange(0,duration+step/2,step)
    t=t0+np.rint(seconds*1e9).astype(np.int64)
    r=np.deg2rad(angle)/2
    q=np.tile([np.cos(r),np.sin(r),0.,0.],(len(t),1))
    return t0,{'imu.quat.t':t,'imu.quat.v':q,'imu.gyro.t':t,'imu.gyro.v':np.zeros((len(t),3))}


def keyed(phase,native,t0):return {m['key']:m for m in phase_metrics(phase,native,0.,1.,t0)}


def test_clean_imu_never_fills_missing_contact_or_geometry():
    t0,native=native_imu()
    metrics=keyed('retreat',native,t0)
    assert metrics['tilt_p95_deg']['value']==0.
    assert metrics['tilt_p95_deg']['assessment']=='within_trial_range'
    for key in ['unexpected_contact_count','hand_clearance_mm','whole_robot_margin_mm','object_disturbance_mm']:
        assert metrics[key]['value'] is None and metrics[key]['assessment']=='unavailable'


def test_trial_limits_measure_tilt_and_ignore_yaw_turning():
    t0,native=native_imu(angle=18.)
    native['imu.gyro.v'][:,2]=3.
    metrics=keyed('transport',native,t0)
    assert metrics['tilt_p95_deg']['value']==pytest.approx(18.,abs=1e-4)
    assert metrics['tilt_longest_s']['value']==pytest.approx(1.)
    assert metrics['tilt_longest_s']['assessment']=='review'
    assert metrics['sway_p95_rad_s']['value']==0.
    assert metrics['held_drift_peak_mm']['value'] is None


def test_gap_breaks_duration_and_insufficient_coverage_cannot_look_clean():
    t0,native=native_imu(angle=18.)
    t=native['imu.quat.t'];keep=((t-t0)/1e9<.4)|((t-t0)/1e9>.7)
    native['imu.quat.t']=t[keep];native['imu.quat.v']=native['imu.quat.v'][keep]
    metrics=keyed('approach',native,t0)
    assert metrics['tilt_p95_deg']['coverage']<.95
    assert metrics['tilt_p95_deg']['state']=='insufficient'
    assert metrics['tilt_p95_deg']['assessment']=='unavailable'
    assert metrics['tilt_longest_s']['value']<.5


def test_native_peak_is_retained_between_uniform_grid_samples():
    t0,native=native_imu(step=.005)
    a=np.deg2rad(30)/2
    native['imu.quat.v'][1]=[np.cos(a),np.sin(a),0,0]
    metrics=keyed('approach',native,t0)
    assert metrics['tilt_peak_deg']['value']==pytest.approx(30.,abs=1e-4)
    assert metrics['tilt_p95_deg']['value']==0.


def test_invalid_quaternion_is_not_normalized_into_valid_pose():
    t0,native=native_imu()
    native['imu.quat.v'][:]=0.
    metrics=keyed('approach',native,t0)
    assert metrics['tilt_p95_deg']['value'] is None
    assert metrics['tilt_p95_deg']['state']=='insufficient'


def test_closing_requires_open_evidence_and_does_not_cross_missing_data():
    values=np.r_[np.zeros(20),np.ones(40)]
    weights=np.full(len(values),.01);valid=np.ones(len(values),bool)
    assert closing_events(values,valid,weights)==1
    assert closing_events(np.ones(60),valid,weights)==0
    valid[20]=False
    assert closing_events(values,valid,weights)==0
    assert longest_run([True,True,False,True],[.1,.1,.1,.1])==pytest.approx(.2)


def test_time_comparison_cannot_bypass_failed_quality_or_unconfirmed_boundaries():
    t0,native=native_imu();m=phase_metrics('grasp',native,0.,1.,t0)
    for confirmed,core in [(True,False),(False,True)]:
        result=with_duration_target(m,1.,2.,confirmed,core)
        row=next(r for r in result if r['key']=='duration_ratio')
        assert row['value'] is None
    row=next(r for r in with_duration_target(m,1.,2.,True,True) if r['key']=='duration_ratio')
    assert row['value']==.5 and row['status_label']=='目标用时内'
    assert next(r for r in m if r['key']=='duration_ratio')['value'] is None
