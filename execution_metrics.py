"""Quantified G1 screening protocol. Trial limits are not certified safe limits.

Uniform-time summaries use bounded alignment; native peaks are retained. Missing
geometry is explicit. Neither an IMU value nor a short duration proves success.
"""
import copy
import math

import numpy as np

VERSION = 1
POLICY = dict(version=VERSION, status='engineering_trial_not_validated', grid_hz=100,
              max_gap_ms=100, minimum_coverage=.95,
              tilt_p95_deg=10., tilt_sustained_deg=15., tilt_sustained_s=.2,
              sway_p95_rad_s=1., hand_open=.2, hand_closed=.6, hand_debounce_s=.15,
              speed_reference_multiplier=1.2, minimum_reference_records=5,
              grasp_error_mm=20., grasp_lift_mm=50., grasp_hold_s=.5,
              held_drift_p95_mm=10., held_drift_peak_mm=20.,
              placement_margin_mm=0., settled_drift_mm=10., settled_window_s=1.,
              retreat_hand_clearance_mm=100., retreat_body_margin_mm=200., retreat_hold_s=1.,
              obstacle_reserve_mm=50.)


def spec(key, label, unit, formula, source, limit=None, op='le', basis='工程筛查初值'):
    return dict(key=key, label=label, unit=unit, formula=formula, source=source,
                limit=limit, operator=op, threshold_basis=basis,
                value=None, state='unavailable', assessment='unavailable',
                status_label='缺必要数据', coverage=None,
                note='等待所需测量输入。')


def metric_contract(phase):
    p=POLICY
    metrics=[
        spec('duration_s','阶段用时','s','实际结束事件时间 − 实际开始事件时间；失败尝试与调整计入。','阶段候选或人工修订边界',basis='报告用时；模型候选边界仍需复核'),
        spec('tilt_p95_deg','身体倾角 P95','°','θ=acos(1−2(qx²+qy²))；对有效时间加权取 P95。','IMU 四元数，wxyz',p['tilt_p95_deg']),
        spec('tilt_peak_deg','身体倾角原生峰值','°','候选区间内所有有效原生四元数对应 θ 的最大值。','原生 IMU 四元数',basis='原生峰值保留；不以单个峰值自动判定失稳'),
        spec('tilt_longest_s','倾角超过 15° 的最长持续时间','s','100 Hz 网格中 θ>15° 的最长连续有效区间；缺失处断开。','IMU 四元数与时间戳',p['tilt_sustained_s'],op='lt'),
        spec('sway_p95_rad_s','横滚/俯仰角速度 P95','rad/s','ω摆动=sqrt(ωx²+ωy²)，按有效时间取 P95；不含正常转向的 yaw。','IMU 陀螺仪',p['sway_p95_rad_s']),
        spec('unexpected_contact_count','非预期碰撞次数','次','确认的非预期机器人—人/物体/环境接触事件数；排除任务允许接触。','连续视觉/场景几何/接触证据，事件级复核',0,basis='任务要求：记录并复核非预期碰撞事件'),
    ]
    if phase!='retreat':
        metrics.append(spec('duration_ratio','用时 / 目标用时','倍','T / T目标；建议 T目标=1.2×至少5条人工确认、同条件优质演示的中位用时。','完整阶段边界及有依据的同条件用时目标',1.,basis='当前审核填写的目标；1.2 倍参考系数为试行建议'))
    if phase in ('approach','retreat'):
        metrics.append(spec('clearance_surplus_mm','非接触障碍间距余量','mm',
            '1000×min[d−(v闭合×τ+v机器人²/(2a制动)+v障碍×v机器人/a制动+3σ+0.05)]；内部按m、s计算，v取朝向彼此的非负速度。',
            '实际定位、机器人外廓、障碍跟踪、实测停止时延τ与保守制动能力a、测距误差σ',0,op='ge',
            basis='附加工程余量50 mm；输入包括停止时延、制动能力与定位误差'))
    if phase=='grasp':
        metrics.extend([
            spec('grasp_error_mm','抓取点误差','mm','实际抓取点与该物体标注目标抓取点的三维距离；抓取区域需先定义。','目标物体与接触点三维位置、TCP/相机标定',p['grasp_error_mm']),
            spec('grasp_attempt_count','实际抓取尝试次数','次','对目标发起抓取至成功抬起期间的尝试数；抓空、重抓计入。','目标跟踪与人工事件标签',1,basis='优选一次完成；两次及以上触发复核，不自动判任务失败'),
            spec('hand_closure_count','右手闭合事件数','次','四指闭合量中位数≤0.2且持续0.15s后，≥0.6且持续0.15s记一次；缺失后重置。','右手实测闭合量，仅为抓取候选',basis='手部闭合事件计数；抓取尝试结合物体状态确认'),
            spec('lift_height_mm','目标抬起高度','mm','物体相对原支撑面的最低高度增量。','物体与支撑面三维位置',p['grasp_lift_mm'],op='ge'),
            spec('lift_hold_s','有效抬起保持时间','s','正确目标抬起至少50mm且持续持有的连续时间。','目标身份、目标跟踪、手物关系',p['grasp_hold_s'],op='ge'),
        ])
    if phase=='transport':
        metrics.extend([
            spec('held_drift_p95_mm','物体相对手位移 P95','mm','以有效抓取后稳定姿态为基准，在手坐标系计算物体位置偏移 P95。','手与物体的同步三维位姿',p['held_drift_p95_mm']),
            spec('held_drift_peak_mm','物体相对手位移峰值','mm','同上，取最大偏移；有意调整抓姿应另标事件。','手与物体的同步三维位姿',p['held_drift_peak_mm']),
            spec('drop_count','掉落次数','次','物体脱离有效抓持并非预期下落的事件数。','连续目标跟踪与事件复核',0,basis='任务要求：无掉落'),
        ])
    if phase=='place':
        metrics.extend([
            spec('placement_margin_mm','放置区域包含裕量','mm','物体三维外形相对允许容纳区域的最小有符号距离；完全位于内部为非负。','目标容器内部区域、物体三维外形与位置',p['placement_margin_mm'],op='ge',basis='当前任务要求入篮；不额外要求位于篮子中心'),
            spec('settled_drift_mm','释放后稳定窗口内最大位移','mm','释放后连续1s窗口内物体任意两时刻的最大位移；有姿态约束时另测旋转。','释放事件及物体连续位姿',p['settled_drift_mm']),
            spec('settled_window_s','释放后连续稳定观察时间','s','物体已进入目标区域且最大位移≤10mm的完整连续观察时间。','连续物体观测；遮挡和缺帧中断计时',p['settled_window_s'],op='ge'),
        ])
    if phase=='retreat':
        metrics.extend([
            spec('hand_clearance_mm','撤回后手臂与物体/容器间距','mm','撤回结束时手臂外形到目标物体及容器的最小三维间距。','实际机器人及目标几何',p['retreat_hand_clearance_mm'],op='ge'),
            spec('whole_robot_margin_mm','整机离开操作区的裕量','mm','机器人完整外廓地面投影相对操作区的最小外部距离；有重叠则为负。','实际基座定位、机器人关节、已标定操作区边界',p['retreat_body_margin_mm'],op='ge'),
            spec('retreat_hold_s','整机离区后持续观察时间','s','手臂已收回且完整外廓在操作区外至少200mm的连续有效观察时间。','完整撤离录像与空间证据',p['retreat_hold_s'],op='ge'),
            spec('object_disturbance_mm','撤离引起的物体最大位移','mm','相对放置稳定后的物体位置，在整个撤离期间计算最大偏移。','物体连续位姿及撤离事件',p['settled_drift_mm']),
        ])
    return metrics


def weighted_percentile(values,weights,q):
    order=np.argsort(values,kind='stable');values=np.asarray(values)[order];weights=np.asarray(weights)[order]
    if not len(values) or weights.sum()<=0:return None
    return float(values[min(len(values)-1,np.searchsorted(np.cumsum(weights),q*weights.sum(),side='left'))])


def longest_run(mask,weights):
    peak=run=0.
    for ok,weight in zip(mask,weights):
        run=run+float(weight) if ok else 0.
        peak=max(peak,run)
    return peak


def closing_events(values,valid,weights):
    """Debounced candidate events; an initial closed hand is not an attempt."""
    opened=closed=0.;armed=False;count=0
    for value,ok,dt in zip(values,valid,weights):
        if not ok:
            opened=closed=0.;armed=False;continue
        if value<=POLICY['hand_open']:
            opened+=dt;closed=0.
            if opened+1e-9>=POLICY['hand_debounce_s']:armed=True
        elif value>=POLICY['hand_closed']:
            closed+=dt;opened=0.
            if armed and closed+1e-9>=POLICY['hand_debounce_s']:
                count+=1;armed=False
        else:opened=closed=0.
    return count


def assess(metric):
    if metric['state']!='measured':
        metric['assessment']='unavailable';metric['status_label']='覆盖不足' if metric['state']=='insufficient' else '缺必要数据'
    elif metric['limit'] is None:
        metric['assessment']='reference_only';metric['status_label']='仅测量'
    else:
        v,t=metric['value'],metric['limit'];op=metric['operator']
        within=v<=t if op=='le' else v<t if op=='lt' else v>=t
        metric['assessment']='within_trial_range' if within else 'review'
        metric['status_label']='试行线内' if within else '触发复核'
    return metric


def phase_metrics(phase,native,start,end,t0):
    # Import lazily: exporter also imports the progress service at module load.
    from exporter import align
    start_ns=int(t0)+round(start*1e9);end_ns=int(t0)+round(end*1e9)
    step=round(1e9/POLICY['grid_hz']);grid=np.arange(start_ns,end_ns,step,dtype=np.int64)
    weights=np.minimum(step,end_ns-grid)/1e9
    metrics=metric_contract(phase);by_key={m['key']:m for m in metrics}

    def aligned(key,width,quaternion=False):
        if key+'.t' not in native or key+'.v' not in native:return None
        t,v=native[key+'.t'],native[key+'.v']
        if t.ndim!=1 or t.dtype.kind not in 'iu' or v.shape!=(len(t),width) or np.any(np.diff(t.astype(np.int64))<0):return None
        v=np.array(v,float,copy=True)
        if quaternion:
            norms=np.linalg.norm(v,axis=1)
            v[(norms<.9)|(norms>1.1)]=np.nan
        return align(t,v,grid,max_gap_ns=round(POLICY['max_gap_ms']*1e6),quaternion=quaternion)

    def put(key,value,valid,source_note=''):
        m=by_key[key];coverage=float(weights[valid].sum()/weights.sum()) if len(weights) else 0.
        m.update(value=None if value is None else round(float(value),5),coverage=round(coverage,5),
                 state='measured' if value is not None and coverage+1e-9>=POLICY['minimum_coverage'] else 'insufficient',
                 note=source_note or '100 Hz有界对齐，数值统计要求有效覆盖率达到95%；缺失处断开。')
        assess(m)

    by_key['duration_s'].update(value=round(end-start,5),state='measured',coverage=1.,note='当前阶段区间用时，实际开始和结束事件仍需核对。')
    assess(by_key['duration_s'])
    q=aligned('imu.quat',4,quaternion=True)
    if q is not None:
        values,valid=q;theta=np.rad2deg(np.arccos(np.clip(1-2*(values[:,1]**2+values[:,2]**2),-1,1)))
        valid &= np.isfinite(theta)
        put('tilt_p95_deg',weighted_percentile(theta[valid],weights[valid],.95),valid)
        put('tilt_longest_s',longest_run(valid&(theta>POLICY['tilt_sustained_deg']),weights) if valid.any() else None,valid)
        t=native['imu.quat.t'];v=np.asarray(native['imu.quat.v'],float);norm=np.linalg.norm(v,axis=1)
        selected=(t>=start_ns)&(t<end_ns)&np.isfinite(v).all(axis=1)&(norm>=.9)&(norm<=1.1)
        raw=v[selected]/norm[selected,None]
        peak=float(np.rad2deg(np.arccos(np.clip(1-2*(raw[:,1]**2+raw[:,2]**2),-1,1))).max()) if len(raw) else None
        put('tilt_peak_deg',peak,valid,'原生样本取峰值，不经过100 Hz抽样；覆盖率按统一时间网格计算。')
    gyro=aligned('imu.gyro',3)
    if gyro is not None:
        values,valid=gyro;speed=np.linalg.norm(values[:,:2],axis=1)
        put('sway_p95_rad_s',weighted_percentile(speed[valid],weights[valid],.95),valid)
    if phase=='grasp':
        hand=aligned('hand.right.state_q',6)
        if hand is not None:
            values,valid=hand;grip=np.median(values[:,2:6],axis=1)
            valid &= np.isfinite(grip)&(grip>=0)&(grip<=1)
            put('hand_closure_count',closing_events(grip,valid,weights) if valid.any() else None,valid,
                '右手四指闭合事件，仅供定位抓取候选；初始已闭合不记一次，缺失后重新等待张开证据。')
    return metrics


def with_duration_target(metrics,duration,target,boundary_confirmed,core_passed):
    metrics=copy.deepcopy(metrics)
    for m in metrics:
        if m['key']!='duration_ratio':continue
        if (target is not None and isinstance(target,(float,int)) and math.isfinite(target) and target>0
                and boundary_confirmed and core_passed):
            m.update(value=round(duration/target,5),state='measured',coverage=1.,note='使用本阶段明确保存的目标用时；目标依据随审核保留。')
            assess(m);m['status_label']='目标用时内' if m['assessment']=='within_trial_range' else '超过目标用时'
        else:m['note']='需先确认完整阶段、核心执行要求并填写目标用时；暂不评价迅速程度。'
    return metrics
