"""Conservative visual task evidence. 2-D containment is never certified success."""
import math

POLICY=dict(target_threshold=.35,basket_threshold=.60,hand_threshold=.25,open_threshold=.15,
            closed_threshold=.45,containment_threshold=.85,settling_observations=3,settling_span_s=.9,
            automatic_score_cap=8.,version='chili-visual-evidence-v1')

def area(box):return max(0,box[2]-box[0])*max(0,box[3]-box[1])

def intersection(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))

def usable(box):
    return len(box)==4 and all(math.isfinite(x) for x in box) and area(box)>0

def observation(row,previous_target=None):
    boxes=[b for b in row.get('detections',[]) if usable(b.get('box',[])) and math.isfinite(b.get('score',float('nan')))]
    targets=sorted((b for b in boxes if ('pepper' in b['label'] or 'chili' in b['label']) and b['score']>=POLICY['target_threshold']),key=lambda b:-b['score'])
    baskets=sorted((b for b in boxes if 'basket' in b['label'] and b['score']>=POLICY['basket_threshold']),key=lambda b:-b['score'])
    hands=[b for b in boxes if 'hand' in b['label'] and b['score']>=POLICY['hand_threshold']]
    width,height=row.get('image_size',[1,1]);diagonal=max(math.hypot(width,height),1)
    def rank(b):
        if previous_target is None:return b['score']
        old,new=previous_target['box'],b['box']
        distance=math.hypot((old[0]+old[2]-new[0]-new[2])/2,(old[1]+old[3]-new[1]-new[3])/2)/diagonal
        return b['score']-.7*distance
    targets.sort(key=rank,reverse=True)
    target=targets[0] if targets else None;basket=baskets[0] if baskets else None
    # Similar-scoring, spatially different objects may include a plant; abstain.
    ambiguous=bool(len(targets)>1 and rank(targets[0])-rank(targets[1])<.08 and intersection(targets[0]['box'],targets[1]['box'])/min(area(targets[0]['box']),area(targets[1]['box']))<.5)
    if ambiguous:target=None
    inside=False;outside=False;near_hand=False
    if target and basket:
        t,b=target['box'],basket['box'];fraction=intersection(t,b)/area(t)
        cx,cy=(t[0]+t[2])/2,(t[1]+t[3])/2
        # Keep away from the lower/front face of the basket and outside its rim.
        inside=bool(fraction>=POLICY['containment_threshold'] and b[0]<cx<b[2] and b[1]<cy<b[1]+.72*(b[3]-b[1]))
        outside=bool(fraction<.05)
    if target:
        near_hand=any(intersection(target['box'],h['box'])/area(target['box'])>.3 and 1.5<area(h['box'])/area(target['box'])<30 for h in hands)
    hand=row.get('hand_closure')
    valid_hand=isinstance(hand,(int,float)) and math.isfinite(hand) and 0<=hand<=1
    return dict(time_s=row['time_s'],target_visible=target is not None,basket_visible=basket is not None,
                target=target,basket=basket,ambiguous=ambiguous,inside_candidate=inside,outside_candidate=outside,
                held_candidate=bool(near_hand and valid_hand and hand>POLICY['closed_threshold']),
                hand_open=bool(valid_hand and hand<POLICY['open_threshold']),hand_valid=valid_hand)

def visual_task_score(rows,task_id,source_outcome=None,hand_summary=None):
    out=dict(version=POLICY['version'],source='grounding_dino_and_measured_hand',score=None,max_score=10,
             state='needs_review',task_result='unknown',completion=None,reason='视觉与手部证据不足，不能确认任务结果',milestones=[],policy=POLICY)
    if task_id!='chili_table_to_basket':
        return {**out,'state':'undefined_task','reason':'任务不匹配，禁止套用辣椒入篮评分'}
    if not rows:return out
    obs=[];previous=None
    for r in sorted(rows,key=lambda r:r['time_s']):
        o=observation(r,previous);obs.append(o)
        if o['target']:previous=o['target']
    # Keep one observation per timestamp; repeated copies cannot prove stability.
    obs=list({o['time_s']:o for o in obs}.values())
    held=any(o['held_candidate'] for o in obs)
    outside_start=bool(obs[0]['target_visible'] and not obs[0]['inside_candidate'])
    end=obs[-3:]
    settled=bool(len(end)==3 and end[-1]['time_s']-end[0]['time_s']>=POLICY['settling_span_s'] and all(o['inside_candidate'] and o['hand_open'] for o in end))
    target_count=sum(o['target_visible'] for o in obs)
    hand_summary=hand_summary or {}
    visible=[o['target']['box'] for o in obs if o['target']]
    width,height=rows[0].get('image_size',[1,1]);diagonal=max(math.hypot(width,height),1)
    stationary=bool(len(visible)>=4 and all(math.hypot((b[0]+b[2]-visible[0][0]-visible[0][2])/2,(b[1]+b[3]-visible[0][1]-visible[0][3])/2)/diagonal<.08 and .5<area(b)/area(visible[0])<2 for b in visible))
    entirely_open=hand_summary.get('max_closure') is not None and hand_summary['max_closure']<POLICY['open_threshold']
    never_closed=bool(sum(o['hand_valid'] and o['hand_open'] for o in obs)>=4 and not held
                      and hand_summary.get('coverage',0)>=.95
                      and (entirely_open or (stationary and hand_summary.get('closed_fraction',1)<.08)))
    if settled and held and outside_start and source_outcome is not False:
        out.update(state='provisional',task_result='completion_candidate',score=8.,reason='网络检测到辣椒连续位于篮框内，手部状态已张开；二维画面只能支持入篮候选，待复核后才能确认满分')
    elif settled and source_outcome is False:
        out.update(reason='视觉入篮候选与采集失败标记冲突，需要换视角复核')
    elif never_closed and target_count>=3 and not any(o['inside_candidate'] for o in obs):
        out.update(state='provisional',task_result='not_completed',score=0.,completion=0.,reason='目标位置在抽帧中保持不变，双手绝大多数时间张开，未发现持物证据')
    elif held and len(end)==3 and sum(o['outside_candidate'] for o in end)>=2 and end[-1]['outside_candidate'] and all(o['hand_open'] and not o['inside_candidate'] for o in end) and end[-1]['time_s']-end[0]['time_s']>=POLICY['settling_span_s']:
        out.update(state='provisional',task_result='not_completed',score=6.,reason='有持物证据，但放手后辣椒连续位于篮框外；入篮未完成')
    elif settled:
        out['reason']='末段出现入篮候选，但缺少可靠的抓取或起始状态证据，不能确认完整任务'
    elif not end[-1]['target_visible']:
        out['reason']='终态辣椒未被可靠定位，可能存在遮挡或漏检；请换视角确认入篮结果'
    out['milestones']=[dict(label='视觉目标与闭合手部重合',observed=held),dict(label='目标连续位于篮框内且手张开',observed=settled)]
    out['evidence']=dict(observations=obs,hand_summary=hand_summary,independent_human_verified=False,automatic_success_certified=False,source_outcome_used_only_as_conflict_gate=True)
    return out
