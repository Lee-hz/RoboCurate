"""Source-traceable evidence adapted from HFlow and trajlens (Apache-2.0).

See THIRD_PARTY_NOTICES.md and static/licenses/{hflow,trajlens}.txt.
Modifications: scan the whole timeline, distinguish raw capture from fixed-rate
export, mask bad/gapped motion steps instead of reconnecting them, and report
unmeasured checks as unknown. Motion facts never classify task success.
"""
import numpy as np

VERSION = 1
SOURCES = {
    'hflow': '296c68ed52aaf186d1ce6d2f69b4e44eb1b11a8b',
    'trajlens_temporal': 'f14ce1c7a56a490ecb1597436f1f6bf1107fcafb',
    'trajlens_score': '4c7180405b4f4661a0105c7417b390d17a121c2a',
}


def fixed_spacing(seconds, fps, tolerance_s=1e-4):
    """Trajlens/LeRobot spacing thresholds, only for declared fixed-rate data.

    Unlike the reference's first-warning break, later failures take priority.
    `seconds` must be episode-relative; never cast epoch nanoseconds to floats.
    """
    t = np.asarray(seconds, dtype=float)
    if t.ndim != 1 or not np.isfinite(fps) or fps <= 0:
        raise ValueError('Expected a one-dimensional timeline and positive fps')
    if len(t) < 2:
        return dict(severity='SKIP', reason='insufficient_timestamps', samples=len(t))
    if not np.isfinite(t).all():
        return dict(severity='FAIL', reason='nonfinite_timestamp', samples=len(t))
    dt = np.diff(t); deviation = np.abs(dt - 1/fps)
    failures = (dt <= 0) | (deviation > 1/fps)
    warnings = deviation > tolerance_s
    level = 'FAIL' if failures.any() else 'WARN' if warnings.any() else 'PASS'
    return dict(severity=level, samples=len(t), tolerance_s=tolerance_s,
                max_deviation_s=float(deviation.max()),
                failure_count=int(failures.sum()), warning_count=int((warnings & ~failures).sum()))


def raw_timing(stamps_ns, expected_hz=None, tolerance_s=.010, gap_factor=3.0):
    """HFlow raw-capture timing facts; no universal reject threshold."""
    t = np.asarray(stamps_ns)
    if t.ndim != 1 or t.dtype.kind not in 'iu':
        raise ValueError('Raw timestamps must be one-dimensional integer nanoseconds')
    if expected_hz is not None and (not np.isfinite(expected_hz) or expected_hz <= 0):
        raise ValueError('Expected frequency must be positive')
    if len(t) < 2:
        return dict(state='not_measured', samples=len(t))
    dt = np.diff(t.astype(np.int64))/1e9
    positive = dt > 0
    period = 1/expected_hz if expected_hz else float(np.median(dt[positive])) if positive.any() else None
    result = dict(state='measured', samples=len(t), nonpositive_dt_count=int((~positive).sum()),
                  tolerance_s=tolerance_s, expected_period_s=period,
                  period_source='declared' if expected_hz else 'positive_median')
    if period is None:
        return result
    result.update(median_dt_s=float(np.median(dt)), max_gap_s=float(max(dt.max(), 0)),
                  period_violation_pct=float(np.mean(np.abs(dt-period)>tolerance_s)*100),
                  gap_count=int(np.sum(dt>gap_factor*period)), gap_factor=gap_factor)
    return result


def motion_facts(stamps_ns, values, dimension_scales=None, max_gap_s=.1,
                 motionless_speed_epsilon=1e-3, final_pose_window_s=.5):
    """HFlow trajectory facts with explicit coverage and no jump over bad rows.

    Raw physical units by default; no per-episode range normalization. Values
    must describe a trajectory (e.g. position), not mixed-unit action deltas.
    These facts are review evidence, never a success or quality-grade oracle.
    """
    t = np.asarray(stamps_ns); x = np.asarray(values, dtype=float)
    if x.ndim == 1: x = x[:, None]
    if t.ndim != 1 or t.dtype.kind not in 'iu' or x.ndim != 2 or len(x) != len(t):
        raise ValueError('Trajectory values and integer timestamps must match')
    if max_gap_s <= 0 or final_pose_window_s <= 0:
        raise ValueError('Time windows must be positive')
    scale = np.ones(x.shape[1]) if dimension_scales is None else np.asarray(dimension_scales, dtype=float)
    if scale.shape != (x.shape[1],) or not np.isfinite(scale).all() or (scale <= 0).any():
        raise ValueError('One finite positive scale is required for each dimension')
    result = dict(state='not_measured', samples=len(t), dimensions=x.shape[1],
                  non_finite_value_count=int((~np.isfinite(x)).sum()),
                  scale_source='raw' if dimension_scales is None else 'user',
                  max_gap_s=max_gap_s, advisory_only=True)
    if len(t) < 2: return result
    dt = np.diff(t.astype(np.int64))/1e9
    if (dt < 0).any():
        result.update(reason='timestamp_reversal', nonpositive_dt_count=int((dt <= 0).sum()))
        return result
    finite = np.isfinite(x).all(axis=1)
    step_valid = finite[:-1] & finite[1:] & (dt > 0) & (dt <= max_gap_s)
    velocity = np.full((len(dt), x.shape[1]), np.nan)
    velocity[step_valid] = np.diff(x/scale, axis=0)[step_valid]/dt[step_valid, None]
    speed = np.linalg.norm(velocity, axis=1)
    result.update(nonpositive_dt_count=int((dt <= 0).sum()), gap_count=int((dt > max_gap_s).sum()),
                  valid_step_count=int(step_valid.sum()), total_step_count=len(dt))
    if not step_valid.any(): return result
    observed_s = float(dt[step_valid].sum())
    mean_speed = float(np.sum(speed[step_valid]*dt[step_valid])/observed_s)
    result.update(state='measured', valid_velocity_s=observed_s,
                  peak_velocity=float(np.max(speed[step_valid])), mean_velocity=mean_speed,
                  motionless_fraction=float(np.sum(dt[step_valid & (speed < motionless_speed_epsilon)])/observed_s))
    changes = np.linalg.norm(np.diff(velocity, axis=0), axis=1)
    changes = changes[np.isfinite(changes)]
    if len(changes):
        result.update(trajectory_change_p95=float(np.percentile(changes, 95)),
                      max_trajectory_change=float(np.max(changes)))
    # Retain the reference definition (unweighted mean over the final window),
    # but only include measured steps; no NaN-to-zero fill.
    last_valid_time = t[1:][step_valid][-1]
    final = step_valid & ((last_valid_time-t[:-1])/1e9 <= final_pose_window_s)
    if final.any():
        end_speed = float(speed[final].mean());result['final_pose_speed'] = end_speed
        if mean_speed > 0:result['final_pose_unsettled_ratio'] = end_speed/mean_speed
    return result


def integrity_summary(checks):
    """Trajlens 1.0 penalties with an explicit applicability/coverage guard.

    Quality-tier findings are advisory and excluded. Unknown is never scored
    as a clean 100. Scores do not override individual hard-stop findings.
    """
    applicable = [c for c in checks if c.get('tier', 'integrity') == 'integrity']
    measured = [c for c in applicable if c['severity'] in ('PASS', 'WARN', 'FAIL')]
    counts = {level:sum(c['severity']==level for c in applicable)
              for level in ('PASS', 'WARN', 'FAIL', 'ERROR', 'SKIP')}
    score = max(0, 100-min(30*counts['FAIL'],60)-min(5*counts['WARN'],20)-10*counts['ERROR']) if measured else None
    state = 'not_measured' if not measured else 'incomplete' if counts['ERROR'] or counts['SKIP'] else 'measured'
    return dict(state=state, score=score, counts=counts, measured_checks=len(measured),
                applicable_checks=len(applicable), source_formula='trajlens-1.0',
                policy_note='Integrity only; task success and motion quality are not assessed')


def value_facts(values, min_run_fraction=.05, min_dimension_samples=11):
    """HFlow repeated-value / unchanged-axis facts, without a freeze verdict.

    Constant targets and quantized hand measurements can repeat legitimately.
    Never infer a stalled publisher from these facts alone, or run them on
    resampled hold channels as though the repetition existed in the source.
    """
    x = np.asarray(values, dtype=float)
    if x.ndim == 1: x = x[:, None]
    if x.ndim != 2: raise ValueError('Expected a sample-by-dimension array')
    result = dict(samples=len(x), dimensions=x.shape[1], nan_count=int(np.isnan(x).sum()),
                  inf_count=int(np.isinf(x).sum()), advisory_only=True)
    if len(x) < 2: return result
    repeated = np.all(x[1:] == x[:-1], axis=1)
    edges = np.diff(np.r_[False, repeated, False].astype(np.int8))
    runs = np.flatnonzero(edges == -1)-np.flatnonzero(edges == 1)
    minimum = max(1, int(np.ceil(min_run_fraction*len(repeated))))
    result.update(repeated_run_count=int(np.sum(runs >= minimum)),
                  longest_repeated_fraction=float(max(runs, default=0)/len(repeated)),
                  repeated_step_pct=float(repeated.mean()*100))
    if len(x) >= min_dimension_samples:
        result['unchanged_dimensions'] = np.flatnonzero(~np.any(x[1:] != x[:-1], axis=0)).tolist()
    return result


def native_reference_checks(native, meta):
    """Read-only G1 evidence. This report never changes saved or automatic grades."""
    timing, values, motion = {}, {}, {}
    streams = ['state.q', 'action.q', 'hand.left.state_q', 'hand.right.state_q',
               'hand.left.cmd_q', 'hand.right.cmd_q']
    streams += ['camera.'+name for name in meta.get('cameras', {})]
    for key in streams:
        if key+'.t' not in native:
            timing[key] = dict(state='not_measured', reason='missing_timestamps');continue
        try:
            timing[key] = raw_timing(native[key+'.t'])
            if key+'.v' in native:values[key] = value_facts(native[key+'.v'])
        except ValueError as e:timing[key] = dict(state='not_measured',reason=str(e))
    for key in ['state.q','hand.left.state_q','hand.right.state_q']:
        if key+'.t' in native and key+'.v' in native:
            try:motion[key] = motion_facts(native[key+'.t'],native[key+'.v'])
            except ValueError as e:motion[key] = dict(state='not_measured',reason=str(e))
    return dict(version=VERSION,sources=SOURCES,timing=timing,values=values,motion=motion,
                source=meta.get('source', {}),affects_grade=False,
                note='HFlow 原始时序与运动测量；trajlens 固定帧率检查仅用于导出网格。运动平滑度、重复值和静止不直接决定等级或任务成败。')
