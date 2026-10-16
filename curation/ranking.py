"""Explicit cohort ranks and non-destructive selection gates (no forced quality)."""
from collections import Counter
import math
import numpy as np
from scipy.stats import rankdata

GRADE_NAMES={'A':'优先候选','B':'常规候选','C':'低优先候选','D':'已筛出 · 未完成','E':'已筛出 · 过程不完整','R':'需复核','U':'未纳入比较'}

def rank_scores(values):
    x=np.asarray(values,float)
    if not np.isfinite(x).all():raise ValueError('Non-finite ranking input')
    if len(x)<2 or np.ptp(x)<1e-10:return np.full(len(x),5.)
    # Midrank empirical percentile: ties stay ties; no min-max stretching.
    return 10*(rankdata(x,method='average')-.5)/len(x)

def eligibility(row,domain):
    t=row['task'];review=row.get('visual_review') or {}
    if domain not in ['sim','real']:return 'U','任务不同或尚未识别，禁止混排'
    if t.get('state')=='incomplete_start':return 'E','任务过程不完整，评分前直接筛出'
    if row.get('outcome') is False:
        return 'D','采集标记为失败，单独保留作失败与恢复资料；不自动删除'
    if domain=='sim':
        if t.get('task_result')=='completed':return 'candidate','物体几何支持完成，进入同任务候选排序'
        if t.get('task_result')=='not_completed':return 'D','物体证据支持未完成；保留失败资料'
        return 'R','仿真终态证据不足或冲突，先复核'
    if t.get('task_result')=='not_completed':return 'D','视觉与手部证据支持未完成，候选结论待复核'
    if row.get('outcome') is True and review.get('task_result')=='completed_review':
        return 'candidate','采集成功标记与抽帧检查一致，进入候选排序'
    return 'R','终态信息待复核'

def stratify(rows,domain,report):
    result={};eligible=[]
    for i,r in enumerate(rows):
        gate,reason=eligibility(r,domain);result[r['id']]=dict(grade=gate if gate!='candidate' else None,reason=reason,cohort=domain,score=None,method='deminf',external_quality_certified=False)
        if gate=='candidate':eligible.append(i)
    vals=np.array(report['scores']['deminf']);ranks=rank_scores(vals[eligible])
    seed_ranks=np.array([rank_scores(np.array(s)[eligible]) for s in report['seed_scores']['deminf']])
    tied=len(eligible)<2 or np.ptp(vals[eligible])<1e-10
    for j,i in enumerate(eligible):
        r=result[rows[i]['id']];score=float(ranks[j]);low,high=float(seed_ranks[:,j].min()),float(seed_ranks[:,j].max())
        grade='B' if tied else 'A' if score>=7.5 else 'B' if score>=5 else 'C'
        r.update(grade=grade,score=round(score,2),rank=int(1+np.sum(vals[eligible]>vals[i])),cohort_size=len(eligible),seed_score_range=[round(low,2),round(high,2)],unstable=high-low>3,raw_deminfs=[s[i] for s in report['seed_scores']['deminf']],qoq_diagnostic=report['scores']['qoq'][i])
    for i,row in enumerate(rows):
        result[row['id']]['grade_label']=GRADE_NAMES[result[row['id']]['grade']]
        result[row['id']]['motion']=row['motion']
    return result

def choose_records(records,cohort,fraction=.5):
    """Return identifiers only. Caller must never delete or relabel source recordings."""
    if cohort not in ('real','sim') or not 0<fraction<=1:raise ValueError('Select one compatible cohort and a valid budget')
    candidates=[r for r in records if r.get('cohort')==cohort and r.get('grade') in ['A','B','C'] and r.get('score') is not None and not r.get('duplicate_of')]
    candidates.sort(key=lambda r:(-r['score'],r['id']))
    n=math.ceil(len(candidates)*fraction)
    if not n:return []
    threshold=candidates[n-1]['score']
    # Do not arbitrarily break tied scores just to hit a quota.
    return [r['id'] for r in candidates if r['score']>=threshold]
