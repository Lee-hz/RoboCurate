"""Repeatable simulation action candidates plus per-attempt quality evidence.

Five semantic classes, arbitrary segment count/order. Uses simulation state,
not the real-banana stage checkpoint. Point containment remains a proxy.
"""
import numpy as np

VERSION=1
LABELS=['接近 / 准备','抓取候选','持物搬运','放置候选','释放后处理','系统回位']
POLICY=dict(closed=.55,opened=.25,lift_m=.04,near_wrist_m=.23,place_zone_m=.35,
            base_motion_window_s=.6,moving_on_m_s=.07,moving_off_m_s=.02,
            release_settle_delay_s=.35,settle_window_s=.5,settle_speed_m_s=.06,
            inside_radius_m=.10,outside_radius_m=.15,inside_z_min_m=-.09,inside_z_max_m=.06,
            source='simulation_state_rules',validated_stage_model=False)


def boolean_runs(mask):
    d=np.diff(np.r_[False,mask,False].astype(int))
    return list(zip(np.flatnonzero(d==1),np.flatnonzero(d==-1)))


def identify(t,target,basket,grip,wrist,base_speed,stop):
    t=np.asarray(t,float);target=np.asarray(target,float);basket=np.asarray(basket,float)
    grip=np.asarray(grip,float);wrist=np.asarray(wrist,float);base_speed=np.asarray(base_speed,float)
    n=len(t)
    if n<2 or any(len(a)!=n for a in (target,basket,grip,wrist,base_speed)) or np.any(np.diff(t)<=0):
        raise ValueError('仿真时序或通道长度无效')
    dt=float(np.median(np.diff(t)));stop=min(max(int(stop),1),n)
    valid=np.isfinite(np.c_[target,basket,grip,wrist,base_speed]).all(axis=1)
    valid &= np.r_[True,np.diff(t)<=max(.1,2*dt)]
    closed=np.zeros(n,bool);state=False
    for i in range(n):
        if not valid[i]:state=False
        elif grip[i]>=POLICY['closed']:state=True
        elif grip[i]<=POLICY['opened']:state=False
        closed[i]=state
    distance=np.linalg.norm(target[:,:2]-basket[:,:2],axis=1)
    in_goal=(distance<=POLICY['inside_radius_m'])&(target[:,2]-basket[:,2]>=POLICY['inside_z_min_m'])&(target[:,2]-basket[:,2]<=POLICY['inside_z_max_m'])
    near_hand=np.linalg.norm(wrist-target,axis=1)<POLICY['near_wrist_m']
    win=max(1,round(POLICY['base_motion_window_s']/dt))
    summed=np.r_[0.,np.cumsum(np.where(valid,base_speed,0.))]
    smooth=(summed[1:]-summed[np.maximum(0,np.arange(n)+1-win)])/np.minimum(win,np.arange(n)+1)
    moving=np.zeros(n,bool);in_motion=False
    for i,v in enumerate(smooth):
        if v>POLICY['moving_on_m_s']:in_motion=True
        elif v<POLICY['moving_off_m_s']:in_motion=False
        moving[i]=in_motion
    held=np.zeros(n,bool);attempts=[];events=[]
    active=closed.copy();active[stop:]=False
    closed_runs=boolean_runs(active)
    for k,(a,b) in enumerate(closed_runs):
        lo=max(0,a-round(.2/dt));baseline=float(np.median(target[lo:a+1,2]))
        raised=target[a:b,2]-baseline>POLICY['lift_m']
        # Observed lift evidence can lapse if the object moves away from the hand.
        lift_seen=np.maximum.accumulate(raised)&near_hand[a:b]
        held[a:b]=lift_seen
        if b>=stop or not valid[b]:continue
        release=float(t[b]);had_lift=bool(lift_seen.any())
        near_goal=distance[b]<POLICY['place_zone_m']
        if not had_lift:
            events.append(dict(kind='grasp_retry',start_s=float(t[a]),end_s=release,
                               label='抓取尝试未形成有效抬起',state='review',
                               detail='手部闭合后再次张开，未观察到相对该次起点至少4cm的有效抬起；需结合画面确认。'))
            continue
        if not near_goal:continue
        next_close=next((int(c) for c,d in closed_runs if c>b),stop)
        hi=min(stop,next_close);window=max(2,round(POLICY['settle_window_s']/dt))
        speed=np.full(n,np.nan)
        good=valid[:-1]&valid[1:]
        speed[1:][good]=np.linalg.norm(np.diff(target,axis=0)[good],axis=1)/np.diff(t)[good]
        inside=(distance<=POLICY['inside_radius_m'])&(target[:,2]-basket[:,2]>=POLICY['inside_z_min_m'])&(target[:,2]-basket[:,2]<=POLICY['inside_z_max_m'])
        outside=distance>POLICY['outside_radius_m']
        evidence=None;classification='unknown'
        for end in range(b+max(window,round(POLICY['release_settle_delay_s']/dt))+1,hi+1):
            start=end-window
            if not valid[start:end].all() or closed[start:end].any() or not np.isfinite(speed[start:end]).all():continue
            if np.percentile(speed[start:end],90)>POLICY['settle_speed_m_s']:continue
            if outside[start:end].all():classification='outside';evidence=(start,end);break
            if inside[start:end].all():classification='inside_candidate';evidence=(start,end);break
        number=len(attempts)+1
        finish=float(t[min(hi,n-1)]) if evidence is None else min(float(t[-1]+dt),float(t[evidence[1]-1]+dt))
        index=min(n-1,hi-1) if evidence is None else evidence[1]-1
        attempt=dict(number=number,release_s=release,observation_end_s=finish,
                     result=classification,next_grasp_s=float(t[next_close]) if next_close<stop else None,
                     settled_xy_distance_m=round(float(distance[index]),4),
                     settled_z_offset_m=round(float(target[index,2]-basket[index,2]),4),
                     source='simulation_target_point_and_hand_command',start_s=float(t[a]))
        attempts.append(attempt)
        label=f'第{number}次放置：'+('偏离目标区域' if classification=='outside' else '支持入篮候选' if classification=='inside_candidate' else '结果证据不足')
        events.append(dict(kind='placement',start_s=release,end_s=finish,label=label,
                           state='issue' if classification=='outside' else 'supported' if classification=='inside_candidate' else 'unknown',
                           detail=f"松手后观察目标点相对篮筐参考点的持续位置；水平距离 {distance[index]*100:.1f} cm。使用明确几何代理，不冒充精确网格包含检测。",attempt=attempt))
    # Classify each time from current evidence, rather than a once-only chain.
    phase=np.zeros(n,int);last_release=None;released_after_lift=False
    for i in range(stop):
        if not valid[i]:phase[i]=-1;continue
        if i and closed[i-1] and not closed[i]:
            last_release=i;released_after_lift=bool(held[max(0,i-2):i].any())
        if closed[i]:
            phase[i]=3 if held[i] and distance[i]<POLICY['place_zone_m'] else 2 if held[i] else 1
        elif last_release is not None and released_after_lift and t[i]-t[last_release]<=1.:
            phase[i]=3  # placement follow-through, not an automatic success
        elif last_release is not None and released_after_lift and (in_goal[i] or (not moving[i] and not near_hand[i])):
            phase[i]=4
        elif near_hand[i]:phase[i]=1
        else:phase[i]=0
    phase[stop:]=5
    # Debounce only tiny label flickers; keep true return/retry intervals.
    edges=np.r_[0,np.flatnonzero(phase[1:]!=phase[:-1])+1,n]
    for a,b in zip(edges[:-1],edges[1:]):
        if a and b<n and (b-a)*dt<.12 and phase[a]>=0 and phase[a-1]==phase[b]:phase[a:b]=phase[a-1]
    edges=np.r_[0,np.flatnonzero(phase[1:]!=phase[:-1])+1,n];segments=[]
    for number,(a,b) in enumerate(zip(edges[:-1],edges[1:])):
        k=int(phase[a]);segments.append(dict(id=f'seg-{number}',stage=k,name=LABELS[k] if k>=0 else '证据缺失',
            start_s=float(t[a]),end_s=float(t[b]) if b<n else float(t[-1]+dt),source=POLICY['source'],quality='not_assessed'))
    # Quality follows the detected segments and never rewrites their identity.
    for event in events:
        at=event['start_s']
        parent=next((s for s in segments if s['start_s']<=at<s['end_s']),None)
        event['segment_id']=parent['id'] if parent else None
        if parent and event['state']=='issue':parent['quality']='issue'
        if parent and event['state'] in ('review','unknown') and parent['quality']!='issue':parent['quality']='review'
        if parent and event['state']=='supported' and parent['quality']=='not_assessed':parent['quality']='supported'
    return dict(phase=phase,segments=segments,attempts=attempts,quality_events=events,
                failed_placements=sum(a['result']=='outside' for a in attempts),
                unknown_placements=sum(a['result']=='unknown' for a in attempts),
                grasp_retry_candidates=sum(e['kind']=='grasp_retry' for e in events),
                policy=POLICY,version=VERSION)
