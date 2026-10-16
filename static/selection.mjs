// Candidate manifests are distinct from final approval and training export.
export function selectCandidates(rows, priorityOnly=false) {
  return rows.filter(r=>r.quality?.grading?.method==='deminf_qualified_v2'
    && (priorityOnly?['A']:['A','B','C']).includes(r.quality.grading.grade)
    && Number.isFinite(r.quality.rating?.score) && !r.curation?.duplicate_of).map(r=>r.id);
}
