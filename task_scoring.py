"""Task evidence for table-to-basket transport. Never infer success from file health.

The simulator policy is deliberately explicit and versioned. Its positional
checks are a conservative proxy for containment, not a collision/contact oracle.
Source success flags are reported as corroboration, never used as score targets.
"""
from pathlib import Path
import json
import numpy as np

VERSION = 'chili-transport-v1'
POLICY = dict(lift_m=.06, basket_radius_m=.10, basket_z_below_m=.09,
              basket_z_above_m=.06, settled_speed_m_s=.06, settle_s=.5,
              source_min_distance_m=.5, completion_weight=8, efficiency_weight=2)

def channel(meta, series, key):
    d = meta['channels'][key]
    a = np.asarray(series, dtype='<f4')
    offset, n, width = int(d['offset']), int(d['samples']), int(d['series'])
    if offset < 0 or n < 1 or width < 1 or offset+n*width > a.size:
        raise ValueError('Invalid channel layout: '+key)
    return a[offset:offset+n*width].reshape(width,n).T.astype(float)

def pending(reason):
    return dict(version=VERSION,state='needs_review',task_result='unknown',score=None,max_score=10,
                completion=None,reason=reason,source='task_evidence',milestones=[],curve=None)

def simulation_task_score(meta, series):
    result=pending('尚无足够任务证据')
    result['policy']=POLICY
    if meta.get('profile')!='g1_sim_lerobot':
        return pending('实操缺少物体真值；需要视觉证据，不能使用仿真评分规则')
    instruction=meta.get('episode',{}).get('instruction','').lower()
    if not all(word in instruction for word in ('chili','basket','table')):
        return pending('任务指令与辣椒跨桌入篮评分协议不匹配')
    try:
        objects=channel(meta,series,'objects.pos')
        names=meta['channels']['objects.pos']['names']
        def pos(name):return objects[:,[names.index(name+'.pos_'+axis) for axis in 'xyz']]
        target,basket=pos('target'),pos('container')
        flags=channel(meta,series,'sim.flags')
        fnames=meta['channels']['sim.flags']['names']
        returning=flags[:,fnames.index('terminal_return')]>.5
        success_flags=flags[:,fnames.index('task_success')]>.5
        hands=np.maximum(channel(meta,series,'hand.left.cmd_q')[:,0],channel(meta,series,'hand.right.cmd_q')[:,0])
        n=len(target)
        if len(flags)!=n or len(hands)!=n:raise ValueError('任务通道的时间轴不一致')
        dt=meta['timeline']['step_ns']/1e9
        if not np.isfinite(dt) or dt<=0:raise ValueError('时间步长无效')
        if not np.isfinite(np.c_[target,basket,hands,flags]).all():raise ValueError('任务证据存在缺失或非有限数值')
    except (KeyError,ValueError,IndexError,TypeError) as exc:
        return pending(str(exc))
    # A prefix ends at the first terminal return; never splice later resets in.
    stop=int(np.flatnonzero(returning)[0]) if returning.any() else n
    if stop<2:return pending('没有有效的任务执行片段')
    t=np.arange(n)*dt
    dist=np.linalg.norm(target[:,:2]-basket[:,:2],axis=1)
    initial=float(np.median(dist[:min(stop,max(1,round(.25/dt)))]))
    if initial<POLICY['source_min_distance_m']:
        result.update(state='incomplete_start',task_result='incomplete_record',reason='记录开始时物体已靠近目标篮；缺少取物和搬运过程，不能按完整任务评分',source_success=bool(success_flags.any()),active_end_s=stop*dt)
        return result
    origin_z=float(np.median(target[:max(1,round(.2/dt)),2]))
    lift=np.clip((target[:,2]-origin_z)/POLICY['lift_m'],0,1)
    # Lift plus a close command is only grasp evidence, not proof of contact.
    grasp=(lift>=1-1e-6)&(hands>.5)
    grasp_seen=np.maximum.accumulate(grasp[:stop])
    transported=np.clip((initial-dist[:stop])/(initial-POLICY['basket_radius_m']),0,1)*grasp_seen
    delta_z=target[:,2]-basket[:,2]
    inside=(dist<=POLICY['basket_radius_m'])&(delta_z>=-POLICY['basket_z_below_m'])&(delta_z<=POLICY['basket_z_above_m'])
    tail=max(2,round(POLICY['settle_s']/dt))
    # Observe settling during terminal return, but don't award robot-return motion.
    speed=np.linalg.norm(np.diff(target,axis=0),axis=1)/dt
    settled=bool(n>=tail and inside[-tail:].all() and np.percentile(speed[-tail+1:],90)<=POLICY['settled_speed_m_s'])
    released=bool(n>=tail and (hands[-tail:]<.25).all())
    complete=bool(grasp_seen[-1] and transported.max()>.95 and settled and released)
    dropped=(target[:stop,2]<origin_z-.15)&~inside[:stop]
    # Current state, not maximum-ever progress: drops and backtracking can regress.
    progress=(.20*grasp_seen+.45*transported+.15*inside[:stop]+.20*(inside[:stop]&(hands[:stop]<.25)))
    progress[dropped]=np.minimum(progress[dropped],.2)
    progress[~grasp_seen]=0
    progress=np.clip(progress,0,1)
    completion=1. if complete else min(float(progress[-1]),.8)
    # Downsample before measuring traveled distance to avoid counting numerical jitter.
    stride=max(1,round(.1/dt)); path=target[:stop:stride]
    path_length=float(np.linalg.norm(np.diff(path,axis=0),axis=1).sum())
    direct=float(np.linalg.norm(target[stop-1]-target[0]))
    efficiency=min(1.,direct/max(path_length,1e-6)) if complete else None
    score=round(8*completion+(2*efficiency if complete else 0),2)
    result.update(state='measured',task_result='completed' if complete else 'not_completed',score=score,completion=completion,reason='物体位置、夹爪指令及末端稳定性支持完整入篮' if complete else '任务未完成；按已观察到的物体搬运进展计分',
        source='simulation_object_geometry',source_success=bool(success_flags.any()),
        source_conflict=bool(success_flags.any())!=complete,
        active_end_s=round(stop*dt,3),efficiency=efficiency,
        evidence=dict(initial_distance_m=initial,final_distance_m=float(np.median(dist[-tail:])),final_height_offset_m=float(np.median(delta_z[-tail:])),path_length_m=path_length,settled=settled,released=released,complete=complete),
        milestones=[dict(label='抬起目标物体',observed=bool(grasp_seen[-1])),dict(label='携物移动到目标篮',observed=bool(transported.max()>.95)),dict(label='松手后物体稳定留在篮内',observed=bool(settled and released))],
        curve=dict(times_s=t[:stop:stride].tolist(),progress=progress[::stride].tolist(),kind='geometry_task_progress',label='物体证据进度（不是 WARP 网络输出）'))
    if result['source_conflict']:
        result.update(state='needs_review',task_result='unknown',reason='几何证据与仿真成功标记不一致；请复核篮边接触及释放状态',score=None)
    return result

def load_snapshot_task(directory):
    directory=Path(directory)
    return simulation_task_score(json.loads((directory/'meta.json').read_text()),np.fromfile(directory/'series.bin',dtype='<f4'))
