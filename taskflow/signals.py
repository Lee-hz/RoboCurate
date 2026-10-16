"""Measured robot-state evidence for VLM prompts; never a task-success oracle.

A G1 adaptation inspired by ProTracer: causal alignment, debounced changes,
kinematic wrist origins and bounded keyframe selection. Not a reproduction of
its change-point optimizer. No command channels or task outcome flags are read.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
from trajectories import wrist_positions
from urdf import parse_urdf

VERSION='g1-state-evidence-v1'
POLICY=dict(grid_hz=20.,max_age_s=.15,derivative_window_s=.2,min_event_s=.15,
            hand_change_per_s=.20,hand_transition_min_change=.10,wrist_motion_m_s=.03,gyro_rad_s=.15,max_lookahead_s=10.)
ALLOWED=('state.q','hand.left.state_q','hand.right.state_q','imu.gyro')
SIDES={'left':'左','right':'右'}
LIMITS=['手指收拢或维持姿态不证明已经握住物体；手指张开不证明物体入篮。',
        '腕部位置由实测关节和URDF计算，坐标系为骨盆，不是世界坐标，也不是标定后的接触点。',
        '身体角速度不代表平移，不能据此确认整机离开操作区域；未使用基座位移、目标物位姿或成功标志。',
        '信号变化只是选帧候选，不是语义阶段边界；阈值用于筛选变化，不是质量合格标准。']


def align_measured(t,v,grid,max_age_ns):
    t=np.asarray(t);v=np.asarray(v,float);grid=np.asarray(grid,dtype=np.int64)
    if t.dtype.kind not in 'iu' or t.ndim!=1 or v.ndim!=2 or len(t)!=len(v) or np.any(np.diff(t.astype(np.int64))<=0):
        raise ValueError('反馈时间戳或数组形状无效（重复、倒序均不插补）')
    out=np.full((len(grid),v.shape[1]),np.nan)
    if not len(t):return out
    ix=np.searchsorted(t,grid,side='right')-1;safe=np.maximum(ix,0)
    ok=(ix>=0)&(grid-t[safe]<=max_age_ns)
    out[ok]=np.where(np.isfinite(v[safe[ok]]),v[safe[ok]],np.nan)
    return out


def smooth(values,width=3):
    out=np.full_like(values,np.nan,dtype=float)
    for i in range(width-1,len(values)):
        block=values[i-width+1:i+1]
        if values.ndim==1:
            if np.isfinite(block).all():out[i]=np.median(block)
        else:
            valid=np.isfinite(block).all(axis=0)
            out[i,valid]=np.median(block[:,valid],axis=0)
    return out


def velocity(values,lag=4,dt=.05):
    out=np.full_like(values,np.nan,dtype=float)
    for i in range(lag,len(values)):
        block=values[i-lag:i+1]
        if values.ndim==1:
            if np.isfinite(block).all():out[i]=(values[i]-values[i-lag])/(lag*dt)
        else:
            valid=np.isfinite(block).all(axis=0)
            out[i,valid]=(values[i,valid]-values[i-lag,valid])/(lag*dt)
    return out


def motion_runs(times,speed,on,off,min_s=.15,signed=False):
    labels=np.full(len(times),9,dtype=int);state=0
    for i,v in enumerate(speed):
        if not np.isfinite(v):state=0;continue
        if signed:
            if v>=on:state=1
            elif v<=-on:state=-1
            elif abs(v)<off:state=0
        else:
            if v>=on:state=1
            elif v<off:state=0
        labels[i]=state
    edges=np.r_[0,np.flatnonzero(labels[1:]!=labels[:-1])+1,len(times)]
    return [(int(a),int(b),int(labels[a])) for a,b in zip(edges[:-1],edges[1:])
            if labels[a] not in (0,9) and (times[b-1]-times[a]+.05)>=min_s-1e-6]


class StateEvidence:
    def __init__(self,library,asset):
        self.library=library;self.asset=asset;self.duration=float(asset['duration_s'])
        self.times=np.arange(0,self.duration,1/POLICY['grid_hz']);self.values={};self.measured={};self.tracks={};self.events=[]
        self.warnings=[];self.channels=[];self.files=[];self.fingerprint=None;self.storage=None
        self.available=False;self.reason='这段视频没有已关联的机器人反馈，保留纯视觉分析。'
        self._load()

    def _signature(self):
        h=hashlib.sha256(VERSION.encode());h.update(json.dumps(POLICY,sort_keys=True).encode())
        for p in self.files:
            h.update(str(p).encode())
            with p.open('rb') as stream:
                for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
        return h.hexdigest()

    def _load(self):
        source=self.asset.get('source',{})
        if source.get('kind')!='recording':return
        try:
            snapshot=bool(source.get('snapshot'))
            if snapshot:
                folder=self.library.task_audit.root/'episodes'/source['id'];path=folder/'series.bin'
            else:
                ref=self.library.ref(source['id']);folder=self.library.cache_dir(ref);path=folder/'native.npz'
            meta_path=folder/'meta.json'
            if not meta_path.is_file() or not path.is_file():
                self.reason='尚无可用状态缓存，请先在数据工作台解析该记录。';return
            meta=json.loads(meta_path.read_text());self.files=[meta_path,path]
            initial_stats={str(p):(p.stat().st_size,p.stat().st_mtime_ns) for p in self.files}
            if not snapshot:
                actual=self.library.fingerprint(ref);cached=meta.get('source',{})
                if cached.get('size_bytes')!=actual['size'] or (cached.get('mtime_ns') is not None and cached['mtime_ns']!=actual['mtime_ns']):
                    self.reason='状态缓存与原记录不一致，需重新解析。';return
            self.storage='resampled_snapshot' if snapshot else 'native_feedback'
            t0=int(meta['timeline']['t0_ns']);grid=t0+np.rint(self.times*1e9).astype(np.int64)
            if snapshot:
                count=int(meta['timeline']['samples']);step=int(meta['timeline']['step_ns']);t=t0+np.arange(count,dtype=np.int64)*step
                data=np.memmap(path,dtype='<f4',mode='r')
                arrays={}
                for key in ALLOWED:
                    ch=meta.get('channels',{}).get(key)
                    if not ch:continue
                    n=int(ch['samples']);width=int(ch['series']);offset=int(ch['offset'])
                    if n!=count or width<1 or offset<0 or offset+n*width>len(data):raise ValueError('状态显示缓存长度不一致')
                    arrays[key+'.t']=t;arrays[key+'.v']=np.asarray(data[offset:offset+n*width]).reshape(width,n).T
                self.warnings.append('状态来自重采样显示缓存，候选时刻不能视为原始传感器的精确事件。')
                self._read_arrays(arrays,meta,grid)
            else:
                with np.load(path,allow_pickle=False) as arrays:self._read_arrays(arrays,meta,grid)
            urdf_path=Path(__file__).resolve().parents[1]/'robot/g1_29dof_rev_1_0.urdf'
            if 'state.q' in self.values and urdf_path.is_file():
                try:
                    desc=parse_urdf(urdf_path);self.files.append(urdf_path)
                    for side in SIDES:
                        pos,valid=wrist_positions(desc,meta['joints']['names'],self.values['state.q'],side+'_wrist_yaw_link')
                        speed=np.linalg.norm(velocity(pos),axis=1)
                        key=side+'_wrist';self.tracks[key]=dict(values=pos,speed=speed,unit='m',kind='wrist_pelvis_fk',side=side)
                        self._events(key,speed,POLICY['wrist_motion_m_s'],signed=False)
                except (ValueError,KeyError) as exc:self.warnings.append('腕部相对机身轨迹不可用：'+str(exc))
            self.available=any(np.isfinite(t['values']).sum()>=2 for t in self.tracks.values());self.reason='' if self.available else '没有单位、时间戳及数据有效性均可核实的状态通道。'
            self.events.sort(key=lambda e:e['start_s'])
            for i,event in enumerate(self.events):event['id']=f'state-event-{i+1:04d}'
            if any((Path(p).stat().st_size,Path(p).stat().st_mtime_ns)!=v for p,v in initial_stats.items()):raise ValueError('读取期间状态文件发生变化')
            self.fingerprint=self._signature()
        except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
            self.values={};self.measured={};self.tracks={};self.events=[];self.available=False
            self.reason='状态增强不可用：'+str(exc)[:200]

    def _read_arrays(self,arrays,meta,grid):
        for key in ALLOWED:
            ch=meta.get('channels',{}).get(key)
            if not ch or key+'.t' not in arrays or key+'.v' not in arrays:
                self.warnings.append(key+'：缺少反馈，本通道未用于判断。');continue
            try:
                v=align_measured(arrays[key+'.t'],arrays[key+'.v'],grid,int(POLICY['max_age_s']*1e9))
                names=ch.get('names',[]);unit=ch.get('unit','')
                if v.shape[1]!=len(names):raise ValueError('通道名称与列数不一致')
                if key=='state.q' and (unit!='rad' or len(names)!=29 or names!=meta.get('joints',{}).get('names')):raise ValueError('身体关节单位或维数不匹配')
                if key=='imu.gyro' and (unit!='rad/s' or len(names)!=3):raise ValueError('角速度单位或维数不匹配')
                self.channels.append(dict(key=key,unit=unit,names=names,coverage=round(float(np.isfinite(v).all(axis=1).mean()),4)))
                self.measured[key]=v
                self.values[key]=smooth(v)
                if key.startswith('hand.'):
                    side=key.split('.')[1];normalized=unit=='0=open 1=closed'
                    if normalized:
                        cols=[names.index(n) for n in ('index','middle','ring','pinky') if n in names]
                        if len(cols)!=4:raise ValueError('多指手缺少四指闭合反馈')
                        grip=np.median(v[:,cols],axis=1);grip[(grip<-.05)|(grip>1.05)]=np.nan
                        grip=np.clip(grip,0,1)
                    elif unit=='sim joint' and v.shape[1]==1:
                        grip=v[:,0];self.warnings.append(key+'：仿真关节读数未映射为张开/闭合，只使用其变化。')
                    else:raise ValueError('手部状态单位未知，不套用闭合判据')
                    grip=smooth(grip);speed=velocity(grip)
                    finite=grip[np.isfinite(grip)]
                    threshold=POLICY['hand_change_per_s'] if normalized else max(.01,float(np.ptp(finite))*.2) if len(finite) else .01
                    track=side+'_hand';self.tracks[track]=dict(values=grip,speed=speed,unit=unit,kind='hand_closure_feedback' if normalized else 'sim_hand_joint',side=side)
                    self._events(track,speed,threshold,signed=True)
                elif key=='state.q':
                    columns=[i for i,n in enumerate(names) if any(x in n for x in ('hip','knee','ankle'))]
                    speed=np.sqrt(np.mean(velocity(self.values[key][:,columns])**2,axis=1))
                    self.tracks['leg_joints']=dict(values=speed,speed=speed,unit='rad/s',kind='leg_joint_motion',side=None)
                    self._events('leg_joints',speed,.2,signed=False)
                elif key=='imu.gyro':
                    speed=np.linalg.norm(self.values[key],axis=1)
                    self.tracks['body_rotation']=dict(values=speed,speed=speed,unit='rad/s',kind='body_rotation',side=None)
                    self._events('body_rotation',speed,POLICY['gyro_rad_s'],signed=False)
            except ValueError as exc:self.warnings.append(key+'：'+str(exc))

    def _events(self,key,speed,threshold,signed):
        track=self.tracks[key]
        for a,b,state in motion_runs(self.times,speed,threshold,threshold*.4,signed=signed,min_s=POLICY['min_event_s']):
            kind=track['kind'];side=track['side'];label=SIDES.get(side,'')
            if kind=='hand_closure_feedback':event_kind='hand_closing' if state>0 else 'hand_opening';label+='手指闭合变化' if state>0 else '手指张开变化'
            elif kind=='sim_hand_joint':event_kind='sim_hand_increase' if state>0 else 'sim_hand_decrease';label+='仿真手关节读数上升' if state>0 else '仿真手关节读数下降'
            elif kind=='wrist_pelvis_fk':event_kind='wrist_motion';label+='腕部相对骨盆运动'
            elif kind=='leg_joint_motion':event_kind='leg_joint_motion';label='下肢关节运动（不代表已知基座位移）'
            else:event_kind='body_rotation';label='身体角速度变化'
            values=track['values'][a:b];change=float(values[-1]-values[0]) if values.ndim==1 else float(np.linalg.norm(values[-1]-values[0]))
            self.events.append(dict(start_s=round(float(self.times[a]),3),end_s=round(min(self.duration,float(self.times[b-1]+.05)),3),kind=event_kind,label=label,side=side,track=key,
                magnitude=round(abs(change),5),change=round(change,5),threshold=round(threshold,5),candidate_only=True))

    def unchanged(self):
        if self.fingerprint and self._signature()!=self.fingerprint:raise ValueError('机器人状态或结构缓存已变化，请重新提交分析')

    def summary(self,start=0.,end=None):
        end=self.duration if end is None else end;mask=(self.times>=start)&(self.times<=end)
        facts=[]
        for key,track in self.tracks.items():
            values=track['values'][mask];valid=np.isfinite(values).all(axis=1) if values.ndim==2 else np.isfinite(values)
            row=dict(track=key,kind=track['kind'],side=track['side'],unit=track['unit'],coverage=round(float(valid.mean()),3) if len(valid) else 0)
            if valid.any():
                observed_times=self.times[mask][valid];row.update(first_observed_s=round(float(observed_times[0]),3),last_observed_s=round(float(observed_times[-1]),3))
                if values.ndim==1:
                    good=values[valid];row.update(start_value=round(float(good[0]),4),end_value=round(float(good[-1]),4),min_value=round(float(good.min()),4),max_value=round(float(good.max()),4))
                else:
                    joins=valid[1:]&valid[:-1];delta=np.linalg.norm(np.diff(values,axis=0)[joins],axis=1)
                    row.update(coordinate_frame='pelvis',observed_path_m=round(float(delta.sum()),4),path_is_not_world_motion=True)
            facts.append(row)
        events=[e for e in self.events if e['start_s']<end and e['end_s']>start]
        return dict(available=self.available,reason=self.reason,version=VERSION,source=self.storage,source_fingerprint=self.fingerprint,
                    start_s=start,end_s=end,facts=facts,events=events[:24],event_count=len(events),limits=LIMITS,warnings=self.warnings)

    def for_model(self,start,end):
        data=self.summary(start,end)
        candidates=[e for e in self.events if e['start_s']<end and e['end_s']>start]
        chosen=sorted(candidates,key=lambda e:(not e['kind'].startswith('hand_'),-e['magnitude']))[:12]
        data['events']=[dict(start_s=max(start,e['start_s']),end_s=min(end,e['end_s']),label=e['label'],kind=e['kind'],ongoing_at_window_start=e['start_s']<start,continues_after_window=e['end_s']>end) for e in sorted(chosen,key=lambda e:e['start_s'])]
        data.pop('limits',None)
        data['event_count']=len(candidates)
        return data

    def public(self):
        value=self.summary();value.update(channels=self.channels,policy=POLICY,candidate_count=len(self.events),events=self.events[:300])
        return value

    def playback(self):
        """Local measured values on a causal grid; these arrays are not VLM input."""
        channels=[]
        for channel in self.channels:
            values=self.measured.get(channel['key'])
            if values is None:continue
            channels.append({**channel,'values':[[round(float(x),6) if np.isfinite(x) else None for x in row] for row in values]})
        return dict(available=bool(channels),reason=self.reason,source=self.storage,source_fingerprint=self.fingerprint,
                    rate_hz=POLICY['grid_hz'],max_age_s=POLICY['max_age_s'],
                    times_s=np.round(self.times,6).tolist(),channels=channels,warnings=self.warnings)

    def observation_end(self,start,end):
        # A measured opening can justify observing the result beyond a coarse
        # edge. A subsequent closing limits that look-ahead; it is not itself
        # proof of a new semantic attempt.
        openings=[e for e in self.events if e['kind']=='hand_opening' and e['magnitude']>=POLICY['hand_transition_min_change'] and start<=e['start_s']<=end]
        if not openings:return min(self.duration,end+1.5)
        opened=openings[-1]
        following=[e['start_s'] for e in self.events if e['kind']=='hand_closing' and e['magnitude']>=POLICY['hand_transition_min_change'] and e['side']==opened['side'] and e['start_s']>opened['end_s']]
        next_close=min(following,default=self.duration)
        if next_close<=end:return min(self.duration,end+1.5)
        return min(self.duration,end+POLICY['max_lookahead_s'],next_close-.05 if following else self.duration)

    def closing_barriers(self):return [e['start_s'] for e in self.events if e['kind']=='hand_closing' and e['magnitude']>=POLICY['hand_transition_min_change']]

    def key_times(self,start,end,budget,core=None):
        if budget<2:raise ValueError('至少需要两个画面采样点')
        a,b=core or (start,end);a=max(start,a);b=min(end,b)
        chosen=list(np.linspace(start,end,max(2,budget//3)))+[a,b]
        if core:chosen.extend(np.linspace(a,b,4).tolist())
        candidates=[]
        for e in self.events:
            if e['end_s']<start or e['start_s']>end:continue
            priority=3 if e['kind'].startswith('hand_') else 2 if e['kind'].startswith('sim_hand') else 1
            for t in (e['start_s']-.5,e['start_s'],e['end_s']):
                if start<=t<=end:candidates.append((priority+min(e['magnitude'],1),t))
        def append(t):
            if len(chosen)<budget and all(abs(t-x)>=.12 for x in chosen):chosen.append(float(t))
        # Keep mandatory coverage bounded before adding event candidates.
        chosen=sorted(set(min(end,max(start,round(float(x),6))) for x in chosen))
        if len(chosen)>budget:chosen=[chosen[i] for i in np.linspace(0,len(chosen)-1,budget).round().astype(int)]
        for _,t in sorted(candidates,key=lambda x:(-x[0],x[1])):append(t)
        for t in np.linspace(start,end,budget):append(t)
        return sorted(chosen)
