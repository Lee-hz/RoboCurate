// Associate results by recording identity; names are not unique source identifiers.
export const REVIEW_MODEL='HORIZON-MiniMax';

export function recordingAudits(overview,recordingId){
  const assets=(overview?.assets||[]).filter(a=>a.source.kind==='recording'&&a.source.id===recordingId);
  const ids=new Set(assets.map(a=>a.id));
  const runs=(overview?.runs||[]).filter(r=>ids.has(r.asset_id));
  return {assets,runs,jobs:(overview?.jobs||[]).filter(j=>ids.has(j.asset_id))};
}

export function preferredRun(runs){return runs.find(r=>r.model===REVIEW_MODEL&&r.analysis_mode==='state')||runs.find(r=>r.model===REVIEW_MODEL)||runs[0]||null;}

export function auditStatus(overview,recordingId){
  if(!overview)return {key:'unavailable',label:'阶段记录暂不可用',detail:'稍后刷新重试'};
  const {runs,jobs}=recordingAudits(overview,recordingId);
  const active=jobs.find(j=>j.kind==='review'&&['queued','running'].includes(j.state));
  const run=preferredRun(runs);
  if(active)return {key:'running',label:'阶段分析中',detail:active.message||'等待分析完成',run};
  const latest=jobs.find(j=>j.kind==='review');
  if(!run&&latest&&['failed','interrupted'].includes(latest.state))return {key:'failed',label:'分析失败',detail:latest.message,run:null};
  if(!run)return {key:'not_started',label:'尚无阶段审核',detail:'选择范本后开始',run:null};
  if(run.model!==REVIEW_MODEL)return {key:'legacy',label:'仅历史模型结果',detail:run.model||'历史模型未标注',run};
  const total=run.summary.segment_count,reviewed=run.reviewed_segments||0;
  const scope=run.analysis_range,range=scope?`${scope.start_s.toFixed(1)}–${scope.end_s.toFixed(1)}s`:'范围见结果';
  return {key:reviewed===total&&total>0?'reviewed':'pending',label:reviewed===total&&total>0?'阶段已复核':'阶段待复核',
    detail:`${range} · 人工 ${reviewed}/${total} 段`,run};
}

export function recordNavigation(record,active,escape){
  return `<div class="record-navigation"><a class="record-back" href="#library">← 数据工作台</a><span>记录审核</span></div>`;
}

// Classify only analyzed attempts; a partial positive result never certifies the full recording.
export function taskOutcome(overview,recordingId){
  if(!overview)return {key:'unavailable',label:'判断暂不可用',detail:'稍后刷新重试'};
  const run=preferredRun(recordingAudits(overview,recordingId).runs);
  if(!run)return {key:'not_started',label:'尚无 VLM 判断',detail:'选择范本后开始'};
  if(run.model!==REVIEW_MODEL)return {key:'legacy',label:'仅有历史模型结果',detail:'尚无 MiniMax 判断'};
  const c=run.summary,scope=run.analysis_range;
  const range=scope?`${scope.start_s.toFixed(1)}–${scope.end_s.toFixed(1)}s`:'范围见详情';
  const detail=`${range} · ${run.reviewed_segments?'含人工复核':'模型建议，待复核'}`;
  if(c.not_completed>0)return {key:'failed',label:`含 ${c.not_completed} 次未完成尝试`,detail};
  if(c.uncertain>0)return {key:'uncertain',label:`${c.uncertain} 段证据不足`,detail};
  if(c.segment_count>0&&c.completed===c.segment_count)return {key:'completed',label:'已分析阶段均完成',detail};
  return {key:'uncertain',label:'尚无明确阶段结论',detail};
}

// Stage-result filters overlap: a failed attempt must not hide uncertain evidence
// elsewhere in the same reviewed range. Legacy models never qualify as MiniMax.
export function matchesTaskOutcome(overview,recordingId,filter){
  if(!filter)return true;
  const run=preferredRun(recordingAudits(overview,recordingId).runs);
  if(!run||run.model!==REVIEW_MODEL)return false;
  if(filter==='failed')return run.summary.not_completed>0;
  if(filter==='uncertain')return run.summary.uncertain>0||taskOutcome(overview,recordingId).key==='uncertain';
  if(filter==='completed')return run.summary.segment_count>0&&run.summary.completed===run.summary.segment_count;
  return false;
}

// A stored decision for a changed source is not a current retention decision.
export function matchesRetention(record,filter){
  if(!filter)return true;
  if(filter==='unreviewed')return !record.review?.grade;
  if(filter==='stale')return !!record.review_stale;
  return !record.review_stale&&record.review?.grade===filter;
}
