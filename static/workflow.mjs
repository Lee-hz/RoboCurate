// UI decisions follow saved review and server readiness. "Ready" means eligible
// to request preflight, never that a training export has already passed checks.
export const reviewLabels = { A: '通过', B: '处理后保留', C: '待复核', D: '排除' };
export const reviewIcons = { A: 'check', B: 'crop', C: 'search', D: 'close' };
export const queues = {
  analyze: { label: '待质检', icon: 'sliders' },
  review: { label: '待复核', icon: 'search' },
  complete: { label: '待完善', icon: 'list' },
  preflight: { label: '可预检', icon: 'export' },
  excluded: { label: '不可用 / 已排除', icon: 'close' },
};
export function hasInstruction(text) {
  return !!String(text || '').trim() && !String(text).toLowerCase().includes('validate v1.4');
}
export function workflowState(record) {
  const grade = record.review.grade;
  if(record.snapshot)return {queue:['D','E'].includes(record.quality.grading?.grade)?'excluded':'review',action:'inspect',label:'查看评分与回放'};
  if (grade === 'D' || ['D','E'].includes(record.quality.grading?.grade))
    return { queue: 'excluded', action: 'inspect', label: '查看原因' };
  if (record.cache !== 'ready')
    return { queue: 'analyze', action: 'analyze', label: record.cache === 'building' ? '质检中' : record.cache === 'error' ? '重试质检' : '运行质检' };
  if (!grade || grade === 'C' || record.review_stale)
    return { queue: 'review', action: 'review', label: record.review_stale ? '重新复核' : '开始复核' };
  if (!record.readiness?.ready)
    return { queue: 'complete', action: 'instruction', label: '完善标注' };
  return { queue: 'preflight', action: 'preflight', label: '导出预检' };
}
export function nextReviewStep(record, draft, dirty) {
  if(record.snapshot)return {action:"inspect",title:"本机只读证据",detail:"可检查质量分级和回放；导出训练包需要原始数据。",button:"查看评分依据"};
  if (['D','E'].includes(record.quality.grading?.grade))
    return { action: 'inspect', title: '先核对数据缺失', detail: '当前数据不满足训练条件，可继续查看原因和保存审核结论。', button: '查看缺失原因' };
  if (record.cache !== 'ready')
    return { action: 'analyze', title: record.cache === 'building' ? '正在进行质检' : '先完成深度质检', detail: '质检完成后查看数据等级与问题位置。', button: record.cache === 'building' ? '质检中' : '运行质检', disabled: record.cache === 'building' };
  if (draft.grade === 'D')
    return { action: dirty ? 'save' : 'inspect', title: dirty ? '保存排除结论' : '此记录已排除', detail: '原始数据保留，排除结论不会删除采集文件。', button: dirty ? '保存结论' : '查看依据' };
  if (!draft.grade || draft.grade === 'C' && !dirty || record.review_stale && !dirty)
    return { action: 'decision', title: record.review_stale ? '重新确认审核结论' : '复核画面并给出结论', detail: '数据质量等级是线索，操作效果需要你结合回放确认。', button: '填写审核结论' };
  if (draft.grade === 'C')
    return { action: 'save', title: '保存当前复核进度', detail: '此记录会继续留在待复核队列。', button: '保存待复核结论' };
  if (!hasInstruction(draft.instruction || record.source_instruction))
    return { action: 'instruction', title: '补充具体任务指令', detail: '描述这段操作要完成的目标，便于后续训练使用。', button: '填写任务指令' };
  if (dirty)
    return { action: 'save', title: '保存本次审核', detail: '保存结论与保留片段后，再运行导出预检。', button: '保存审核' };
  if (record.readiness?.ready)
    return { action: 'preflight', title: '可以运行导出预检', detail: '基础条件已满足；预检通过后再创建训练包。', button: '运行导出预检' };
  return { action: 'inspect', title: '核对剩余条件', detail: (record.readiness?.blockers || []).join('；') || '查看当前质检结果后继续。', button: '查看依据' };
}
