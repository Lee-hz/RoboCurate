"""Expose the one current quality score through the existing workbench schema."""
import copy

def project_quality(original,curation=None):
    q=copy.deepcopy(original);c=curation or dict(grade='U',grade_label='待任务准入',score=None,reason='尚无当前任务的准入与质量排序结果')
    if q.get('technical',{}).get('status')=='error':
        c=dict(grade='D',grade_label='已筛出 · 数据损坏',score=None,reason='原始数据无法读取，不能进入质量排序')
    grade=c.get('grade','U');score=c.get('score') if grade in ('A','B','C') else None
    # Keep technical facts, but do not retain legacy numeric ratings as a competing score.
    q['technical_diagnostics']=dict(metrics=copy.deepcopy(q.get('grading',{}).get('metrics',{})),checks=copy.deepcopy(q.get('grading',{}).get('checks',[])))
    q['score']=score;q['suggested_grade']=grade
    q['rating']=dict(version=4,method='deminf_qualified_v2',state='ready' if score is not None else 'excluded' if grade in ('D','E') else 'pending',score=score,max_score=10,dimensions=[],scope='完整任务候选内的质量相对排序；完整度不计分、不加权',reason=c.get('reason',''))
    q['grading']=dict(version=2,method='deminf_qualified_v2',grade=grade,label=c.get('grade_label','待任务准入'),state='evaluated' if score is not None else 'excluded' if grade in ('D','E') else 'pending',summary=c.get('reason',''),metrics={},checks=[],reasons=[])
    return q
