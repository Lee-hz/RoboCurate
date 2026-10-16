"""Validate model proposals as data. Never execute text returned by a VLM."""
import copy
import math
import re

VERSION=1
STATES=('completed','not_completed','uncertain')


def text(value,name,limit=2000,empty=False):
    if not isinstance(value,str) or len(value)>limit or (not value.strip() and not empty):
        raise ValueError(name+'缺失或格式无效')
    return value.strip()


def strings(value,name,limit=20):
    if not isinstance(value,list) or len(value)>limit:raise ValueError(name+'格式无效')
    return [text(v,name,1000) for v in value]


def number(value,name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(name+'必须是有限数值')
    return float(value)


def task_spec(raw):
    if not isinstance(raw,dict):raise ValueError('任务说明必须为对象')
    stages=raw.get('stages')
    if not isinstance(stages,list) or not 1<=len(stages)<=30:raise ValueError('阶段类别需要1至30项')
    clean=[];seen=set()
    for s in stages:
        if not isinstance(s,dict):raise ValueError('阶段定义无效')
        key=text(s.get('id'),'阶段标识',60)
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',key) or key in seen:raise ValueError('阶段标识重复或无效')
        seen.add(key)
        criteria=strings(s.get('success_criteria'),'阶段目标条件',10)
        if not criteria:raise ValueError('每个阶段至少需要一个可观察的目标条件')
        clean.append(dict(id=key,name=text(s.get('name'),'阶段名称',100),goal=text(s.get('goal'),'阶段目标'),
                          success_criteria=criteria,repeatable=True))
    return dict(version=VERSION,task_name=text(raw.get('task_name'),'任务名称',150),
                task_goal=text(raw.get('task_goal'),'任务目标'),objects=strings(raw.get('objects',[]),'任务对象'),
                stages=clean,uncertainties=strings(raw.get('uncertainties',[]),'待澄清要求'),
                origin=raw.get('origin','vlm_proposal') if raw.get('origin')=='human_edited' else 'vlm_proposal')


def _proof(value,frames,start,end):
    if not isinstance(value,list) or len(value)>20:raise ValueError('画面证据列表无效')
    out=[]
    for key in value:
        if not isinstance(key,str) or key not in frames:raise ValueError('模型引用了未提供的画面证据')
        f=frames[key]
        if not start-1.501<=f['time_s']<=end+1.501:raise ValueError('画面证据不在动作段或前后观察范围内')
        if key not in out:out.append(key)
    return out


def segments(raw,spec,start,end,frames,verified=False,evidence_window=None,barriers=(),require_observability=False):
    """Variable ordering/repetition, conservative gap filling and goal evidence."""
    if not isinstance(raw,list) or len(raw)>200:raise ValueError('模型分段列表无效')
    stages={s['id']:s for s in spec['stages']};frame_map={f['id']:f for f in frames}
    out=[];cursor=float(start)

    def unknown(a,b):
        return dict(stage_id=None,name='未识别区间',goal='',start_s=a,end_s=b,completion='uncertain',
                    reason='此区间没有完整的阶段或目标证据。',evidence_frame_ids=[],criteria_results=[],origin='coverage_guard')

    for row in raw:
        if not isinstance(row,dict):raise ValueError('动作段格式无效')
        a=number(row.get('start_s'),'起点');b=number(row.get('end_s'),'终点')
        original_a,original_b=a,b
        if start-.001<=a<start:a=float(start)
        if end<b<=end+.001:b=float(end)
        if a<start-1e-6 or b>end+1e-6 or b-a<=1e-9 or (row.get('stage_id') is not None and b-a<.05):raise ValueError('模型分段越界或动作段不足0.05秒')
        if a<cursor-1e-6:raise ValueError('模型分段乱序或重叠')
        if a>cursor+1e-6:out.append(unknown(cursor,a))
        key=row.get('stage_id')
        if key is not None and key not in stages:raise ValueError('模型使用了任务说明之外的阶段')
        stage=stages.get(key)
        lower,upper=a-1.501,b+1.501
        if evidence_window is not None:
            lower=max(float(evidence_window[0]),lower);upper=float(evidence_window[1])
            future=[float(t) for t in barriers if float(t)>b+.001]
            if future:upper=min(upper,max(b,min(future)-.05))
        def proof(value):
            if evidence_window is None:return _proof(value,frame_map,a,b),[]
            supplied=_proof(value,frame_map,float(evidence_window[0]),float(evidence_window[1]))
            rejected=[key for key in supplied if not lower-1e-6<=frame_map[key]['time_s']<=upper+1e-6]
            return [key for key in supplied if key not in rejected],rejected
        evidence,rejected=proof(row.get('evidence_frame_ids',[]))
        criteria=[];result='uncertain'
        if verified and stage:
            supplied=row.get('criteria_results',[])
            if not isinstance(supplied,list):raise ValueError('阶段目标检查结果无效')
            mapped={}
            for c in supplied:
                if not isinstance(c,dict) or type(c.get('criterion_index')) is not int:raise ValueError('目标条件编号无效')
                index=c['criterion_index']
                if index in mapped or not 0<=index<len(stage['success_criteria']):raise ValueError('目标条件编号重复或越界')
                status=c.get('status')
                if status not in STATES:raise ValueError('目标判断状态无效')
                ids,discarded=proof(c.get('evidence_frame_ids',[]))
                visibility=c.get('observability','unknown')
                if require_observability and visibility!='direct':status='uncertain'
                if discarded:status='uncertain'
                # A claimed success/failure without a supplied frame is unknown.
                if status!='uncertain' and not ids:status='uncertain'
                mapped[index]=dict(criterion_index=index,criterion=stage['success_criteria'][index],status=status,
                                   evidence_frame_ids=ids,reason=text(c.get('reason',''),'目标依据',2000,empty=True))
                if require_observability:
                    mapped[index].update(observability=visibility if visibility in ('direct','limited','unknown') else 'unknown',model_status=c.get('status'),rejected_evidence_frame_ids=discarded,
                        guard_note='观测不充分，保留为证据不足。' if visibility!='direct' else '引用跨越下一次闭合候选或不在允许观察范围内，保留复核。' if discarded else '')
            for index,criterion in enumerate(stage['success_criteria']):
                criteria.append(mapped.get(index,dict(criterion_index=index,criterion=criterion,status='uncertain',
                    reason='模型未提供该条件的判断依据。',evidence_frame_ids=[])))
            statuses=[c['status'] for c in criteria]
            result='not_completed' if 'not_completed' in statuses else 'completed' if all(s=='completed' for s in statuses) else 'uncertain'
            evidence=list(dict.fromkeys(evidence+[f for c in criteria for f in c['evidence_frame_ids']]))
        out.append(dict(stage_id=key,name=stage['name'] if stage else '未识别区间',goal=stage['goal'] if stage else '',
                        start_s=a,end_s=b,completion=result,criteria_results=criteria,evidence_frame_ids=evidence,
                        reason=text(row.get('reason',''),'分段依据',2000,empty=True),origin='vlm_analysis',
                        new_attempt=row.get('new_attempt') is True,boundary_status='estimated_from_sampled_frames'))
        if a!=original_a or b!=original_b:out[-1]['boundary_rounding_correction']=dict(original_start_s=original_a,original_end_s=original_b,max_correction_s=.001)
        if evidence_window is not None:out[-1]['observation_window']=dict(start_s=lower,end_s=upper,rejected_evidence_frame_ids=rejected)
        cursor=b
    if cursor<end-1e-6:out.append(unknown(cursor,end))
    for i,s in enumerate(out):s['id']=f'segment-{i+1:03d}'
    return out


def apply_human_review(result,review):
    out=copy.deepcopy(result)
    for segment in out['segments']:
        manual=review.get(segment['id'])
        segment['effective_completion']=manual['completion'] if manual else segment['completion']
        segment['human_review']=manual
    counts={s:sum(x['effective_completion']==s for x in out['segments']) for s in STATES}
    out['summary']=dict(segment_count=len(out['segments']),**counts)
    return out


def coalesce_continuations(parts):
    """Adjacent pieces of one continuing action are not extra successful attempts.

    Explicit retries and any observed failed attempts are always kept separate.
    For a joined action, use the final piece's goal verdict and retain all earlier
    observations and fragments. Earlier success must not erase later uncertainty.
    """
    out=[]
    for original in parts:
        part=copy.deepcopy(original)
        if (out and part['stage_id'] is not None and out[-1]['stage_id']==part['stage_id']
            and not part.get('new_attempt',False) and abs(out[-1]['end_s']-part['start_s'])<1e-5
            and out[-1]['completion']!='not_completed'):
            before=out.pop()
            fragments=before.get('continuation_fragments',[copy.deepcopy(before)])+part.get('continuation_fragments',[copy.deepcopy(part)])
            part.update(start_s=before['start_s'],new_attempt=before.get('new_attempt',False),continuation_fragments=fragments,
                evidence_frame_ids=list(dict.fromkeys(before['evidence_frame_ids']+part['evidence_frame_ids'])),
                reason='连续动作跨观察区间合并。最终目标判断：'+part['reason'],origin='continuation_reconciliation')
        out.append(part)
    for i,part in enumerate(out):part['id']=f'segment-{i+1:03d}'
    return out
