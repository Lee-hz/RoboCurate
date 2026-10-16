"""Human-label-only evaluation. Never treat VLM proposals as ground truth."""
import json


def evaluate(run,labels):
    if labels.get('annotation_status')!='human_confirmed' or not labels.get('reviewer'):
        raise ValueError('需要独立人工确认的标注；模型预标注不能作为验收真值')
    result=run.get('model_result') or run['result']
    if labels.get('source_fingerprint')!=result.get('source_fingerprint'):raise ValueError('标注和预测的数据源不一致')
    if labels.get('template_id')!=run['template_id'] or labels.get('template_revision')!=run['template_revision']:
        raise ValueError('标注和预测必须使用同一任务定义版本')
    if not labels.get('segments'):raise ValueError('没有已确认的阶段标注')
    scope=labels['evaluation_range'];a,b=scope['start_s'],scope['end_s']
    predicted_scope=result.get('analysis_range',scope)
    if predicted_scope['start_s']>a or predicted_scope['end_s']<b:raise ValueError('预测未覆盖人工验收范围')
    truth=[s for s in labels['segments'] if s.get('stage_id') is not None]
    if not truth:raise ValueError('标注中没有任务阶段')
    if any(s.get('completion') not in ('completed','not_completed','uncertain') or not a<=s['start_s']<s['end_s']<=b for s in truth):
        raise ValueError('人工阶段区间或结论无效')
    pred=[s for s in result['segments'] if s.get('stage_id') is not None and s['start_s']<b and s['end_s']>a]
    candidates=[]
    for i,t in enumerate(truth):
        for j,p in enumerate(pred):
            if t['stage_id']!=p['stage_id']:continue
            overlap=max(0,min(t['end_s'],p['end_s'])-max(t['start_s'],p['start_s']))
            union=max(t['end_s'],p['end_s'])-min(t['start_s'],p['start_s'])
            if overlap/union>=.25:candidates.append((overlap/union,i,j))
    matched={};used=set()
    for iou,i,j in sorted(candidates,reverse=True):
        if i not in matched and j not in used:matched[i]=j;used.add(j)
    rows=[];errors=[]
    for i,t in enumerate(truth):
        p=pred[matched[i]] if i in matched else None
        prediction=p['completion'] if p else 'uncertain'
        if p is None and t['completion']=='not_completed':
            for other in pred:
                overlap=max(0,min(t['end_s'],other['end_s'])-max(t['start_s'],other['start_s']))
                if other['stage_id']==t['stage_id'] and other['completion']=='completed' and overlap/(t['end_s']-t['start_s'])>=.5:
                    prediction='completed';break
        rows.append(dict(truth=t['completion'],prediction=prediction,matched=p is not None))
        if p:errors.extend([abs(t['start_s']-p['start_s']),abs(t['end_s']-p['end_s'])])
    failed=[r for r in rows if r['truth']=='not_completed'];passed=[r for r in rows if r['prediction']=='completed']
    def ratio(n,d):return n/d if d else None
    return dict(labelled_segments=len(truth),matched_segments=len(matched),unmatched_predictions=len(pred)-len(used),
        segment_recall_at_iou_025=ratio(len(matched),len(truth)),segment_precision_at_iou_025=ratio(len(matched),len(pred)),
        failure_as_completed_rate=ratio(sum(r['prediction']=='completed' for r in failed),len(failed)),
        failure_detection_recall=ratio(sum(r['prediction']=='not_completed' for r in failed),len(failed)),
        completed_precision_on_matched_labels=ratio(sum(r['truth']=='completed' for r in passed),len(passed)),
        uncertain_fraction=ratio(sum(r['prediction']=='uncertain' for r in rows),len(rows)),
        mean_boundary_error_s=sum(errors)/len(errors) if errors else None,
        matching='same template stage id, one-to-one greedy temporal IoU >= .25',
        scope='metrics on human-labelled range only; no metric is an overall safety certificate')
