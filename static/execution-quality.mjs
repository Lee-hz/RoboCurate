// Execution findings are saved independently of stage classification and grades.
const choices=[['pending','待审核'],['pass','符合'],['fail','存在问题'],['unknown','无法判断']];
const labels={pending:'待审核',pass:'符合',fail:'存在问题',unknown:'证据不足',blocked:'先处理执行问题'};
const seconds=v=>Number.isFinite(v)?`${v.toFixed(2)} s`:'未定位';

export function quantitativeHTML(phase,e){
  const metrics=phase.quantitative||[],measured=metrics.filter(m=>m.state==='measured').length;
  const flagged=metrics.filter(m=>m.assessment==='review').length;
  return `<details class="execution-quant-${e(phase.id)} execution-quant"><summary>量化指标 · 已测 ${measured}/${metrics.length}${flagged?` · ${flagged} 项提醒`:''}</summary>
    <p>指标按工程筛查阈值提示复核，缺少必要输入时显示未测。</p>
    <div class="execution-quant-list">${metrics.map(m=>`<article data-execution-metric="${e(m.key)}"><div class="execution-quant-row"><span>${e(m.label)}<small>${m.limit===null?'报告测量值':`试行 ${m.operator==='ge'?'≥':m.operator==='lt'?'<':'≤'} ${m.limit} ${e(m.unit)}`}</small></span><span>${m.value===null?'—':`${Number(m.value.toFixed(3))} ${e(m.unit)}`}<small data-metric-assessment="${e(m.assessment)}">${e(m.status_label)}</small></span></div>
      <details class="execution-metric-${e(phase.id)}-${e(m.key)}"><summary>计算定义${m.coverage!==null?` · 覆盖 ${(m.coverage*100).toFixed(1)}%`:''}</summary><p>${e(m.formula)}</p><p>依据：${e(m.source)}</p><p>${e(m.threshold_basis)}</p><p>${e(m.note||'')}</p></details></article>`).join('')}</div></details>`;
}

export function executionQualityHTML(panel){
  const e=panel.escape,r=panel.execution;
  if(!r)return `<section class="execution-quality"><h4>阶段执行质检</h4><p role="status">${e(panel.executionError||'正在读取原生数据与执行标准…')}</p>${panel.executionError?'<button data-execution-reload>重新读取</button>':''}</section>`;
  return `<section class="execution-quality" aria-label="阶段执行质检"><div class="execution-heading"><h4>阶段执行质检</h4><span data-execution-state="${e(r.state)}">${e(r.state_label)}</span></div>
    <p class="execution-intro">接近安全 · 抓取准确 · 搬运稳定 · 放置准确 · 整机安全撤离</p>
    <p class="execution-summary">${r.summary.confirmed} / ${r.summary.phases} 段已确认符合 · ${r.summary.issues} 段存在问题。用时和运动指标自动测量，执行要求逐项审核。</p>
    ${r.review_stale?'<p class="execution-warning">数据或分析依据已变化，原审核保留在历史中；当前结论需要重新确认。</p>':''}
    ${r.phases.map(p=>{
      const draft=panel.executionDrafts?.[p.id]||p.decision||{},missing=p.start_s===null;
      return `<details class="execution-${e(p.id)} execution-phase" data-execution-phase="${e(p.id)}"><summary><span><b>${e(p.name)}</b><small>${e(p.goal)}</small></span><span class="execution-phase-status"><span>${seconds(p.duration_s)}</span><small data-execution-state="${e(p.state)}">${e(p.state_label)}</small></span></summary>
        <p class="execution-boundary">${e(p.boundary)}</p>
        ${missing?'<p>模型没有定位到此阶段。可查看录像后填写实际区间；未记录到时保留证据不足。</p>':''}
          <div class="execution-range"><span>${p.interval_source==='human_corrected'?'人工修订':'模型候选'} ${seconds(p.start_s)} – ${seconds(p.end_s)}</span><button data-execution-preview="${e(p.id)}">回看阶段</button></div>
          <div class="execution-window"><label>起点（秒）<input type="number" data-execution-start min="0" max="${r.recording_duration_s}" step="0.01" value="${draft.start_s??p.start_s??''}"></label><label>终点（秒）<input type="number" data-execution-end min="0" max="${r.recording_duration_s}" step="0.01" value="${draft.end_s??p.end_s??''}"></label></div>
          ${p.key==='retreat'?'<p class="execution-warning">核对手臂收回、整机离开操作区及完整观察区间。</p>':''}
          <p class="execution-boundary">可以修订范围。保存后重新计算用时和运动指标；录像未覆盖完整过程时保留无法判断。</p>
          ${quantitativeHTML(p,e)}
          <div class="execution-checks">${p.checks.filter(c=>c.key!=='pace').map(c=>`<label><span>${e(c.label)}<small>${e(c.help)}</small></span><select data-execution-check="${e(c.key)}" aria-label="${e(p.name+'：'+c.label)}">${choices.map(([value,text])=>`<option value="${value}" ${(draft.checks?.[c.key]||c.status)===value?'selected':''}>${text}</option>`).join('')}</select></label>`).join('')}</div>
          <label class="execution-confirm"><input type="checkbox" data-execution-boundary ${draft.boundary_confirmed?'checked':''}>已确认所填区间覆盖该阶段完整过程</label>
          ${p.key!=='retreat'?`<div class="execution-pace"><label>同条件目标用时（秒）<input type="number" data-execution-target min="0.01" max="3600" step="0.01" value="${draft.target_s??''}" placeholder="尚未设定"></label><label>目标用时依据<input data-execution-basis maxlength="2000" value="${e(draft.pace_basis||'')}" placeholder="参考记录、相同距离及操作条件"></label><p>迅速完成：${e(labels[p.checks.find(c=>c.key==='pace')?.status]||'待审核')}。先确认执行要求与阶段范围，再比较用时；此处显示上次保存后的判断。</p></div>`:''}
          <label class="execution-note">审核依据<textarea data-execution-note maxlength="2000" rows="2" placeholder="记录观察到的动作、问题时间和区域边界">${e(draft.note||'')}</textarea></label>
          <div class="execution-save"><small data-execution-dirty>${panel.executionDrafts?.[p.id]?'有未保存修改':draft.reviewed_at?'人工审核已保存':'尚未保存人工结论'}</small><button data-execution-save="${e(p.id)}">保存本阶段审核</button></div>
          <details class="execution-evidence-${e(p.id)} execution-evidence"><summary>运动指标与问题线索 · ${p.events.length} 项提醒</summary><p>原生数据测量，仅作审核依据；数值大小不直接证明安全或接触质量。</p><dl>${p.metrics.map(m=>`<div><dt>${e(m.label)}</dt><dd>${m.value===null?'未测得':`${m.value.toFixed(3)} ${e(m.unit)}`}</dd></div>`).join('')}</dl>
            ${p.events.length?`<ul>${p.events.slice(0,20).map(event=>`<li><button data-execution-seek="${event.overlap_start_s}">${seconds(event.overlap_start_s)} · ${e(event.label)}</button><small>${e(event.detail)}</small></li>`).join('')}</ul>${p.events.length>20?`<p>共 ${p.events.length} 项，其他问题可在原质检面板查看。</p>`:''}`:'<p>当前规则未在此区间产生事件；执行要求仍需核验。</p>'}</details>
        </details>`;
    }).join('')}
    <details class="execution-method"><summary>判断方式与数据条件</summary><p>按安全、准确、稳定和效率逐项确认，优先处理已定位的问题。</p>${r.limitations.map(t=>`<p>${e(t)}</p>`).join('')}<p>执行审核、记录等级和导出预检分别保存。</p></details>
  </section>`;
}

function decisionFrom(form){
  const target=form.querySelector('[data-execution-target]')?.value||'';
  return {checks:Object.fromEntries([...form.querySelectorAll('[data-execution-check]')].map(el=>[el.dataset.executionCheck,el.value])),
    start_s:form.querySelector('[data-execution-start]')?.value===''?null:Number(form.querySelector('[data-execution-start]')?.value),
    end_s:form.querySelector('[data-execution-end]')?.value===''?null:Number(form.querySelector('[data-execution-end]')?.value),
    boundary_confirmed:!!form.querySelector('[data-execution-boundary]')?.checked,
    target_s:target===''?null:Number(target),pace_basis:form.querySelector('[data-execution-basis]')?.value||'',
    note:form.querySelector('[data-execution-note]')?.value||''};
}

export function bindExecutionQuality(panel){
  const host=panel.host;
  host.querySelector('[data-execution-reload]')?.addEventListener('click',()=>panel.loadExecution());
  host.querySelectorAll('[data-execution-preview]').forEach(b=>b.onclick=()=>{
    const p=panel.execution.phases.find(x=>x.id===b.dataset.executionPreview);
    const d=decisionFrom(b.closest('[data-execution-phase]'));
    if(p&&Number.isFinite(d.start_s)&&Number.isFinite(d.end_s)&&0<=d.start_s&&d.start_s<d.end_s&&d.end_s<=panel.episode.duration_s)
      panel.preview?panel.preview(d.start_s,d.end_s):panel.seek(d.start_s);
    else panel.toast('请先填写有效的阶段时间范围',true);
  });
  host.querySelectorAll('[data-execution-seek]').forEach(b=>b.onclick=()=>panel.seek(Number(b.dataset.executionSeek)));
  host.querySelectorAll('[data-execution-phase]').forEach(form=>{
    const id=form.dataset.executionPhase;
    form.querySelectorAll('input,select,textarea').forEach(el=>el.addEventListener('input',()=>{
      panel.executionDrafts[id]=decisionFrom(form);
      form.querySelector('[data-execution-dirty]').textContent='有未保存修改';
    }));
    const button=form.querySelector('[data-execution-save]');
    if(button)button.onclick=async()=>{
      if(panel.executionSaving)return;
      const report=panel.execution,model=panel.selected,generation=panel.generation;
      panel.executionSaving=true;button.disabled=true;
      try{
        const updated=await panel.api('/api/execution-quality/review',{ep:panel.episode.id,model_id:model,
          signature:report.signature,revision:report.review.revision,phase_id:id,decision:decisionFrom(form)});
        if(panel.closed||panel.selected!==model||panel.generation!==generation)return;
        delete panel.executionDrafts[id];panel.execution=updated;panel.render();panel.toast('本阶段执行审核已保存');
      }catch(error){panel.toast(error.message,true);}
      finally{panel.executionSaving=false;if(button.isConnected)button.disabled=false;}
    };
  });
}
