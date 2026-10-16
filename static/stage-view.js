import {stageAt,stageEvidenceAt,stageColors,stageInputSummary,reviewTarget} from './stage-data.mjs';
import {executionQualityHTML} from './execution-quality.mjs';

const shortNames=['接近','抓取','搬运','放置','释放后'];
const reasonHelp={'输入不完整':'当前采样缺少相机或关节输入，需结合原始画面核对。','模型意见分歧':'三个网络对阶段的判断不一致。','把握度较低':'当前预测把握度低于 80%。','阶段证据不足':'概率校准前的原始输出仍有不确定信号，较高把握度也需要复核。','无有效图像':'该采样没有足够的有效图像，模型没有给出阶段。','阶段切换附近':'阶段标签发生变化，需核对切换位置。','阶段过渡待核查':'辅助模型提示可能发生阶段过渡，精确时刻仍需核查。'};
export const timeLabel=t=>`${Number(t).toFixed(1)} s`;

export function stageResultHTML(panel){
  const r=panel.result,e=panel.escape,s=r.summary,ranges=panel.reviewRanges,visible=panel.filteredReviewRanges();
  const buttons=r.stage_names.map((name,k)=>{
    const first=r.stage_segments.find(p=>p.stage===k);
    return `<button class="stage-step" data-stage-jump="${k}" ${first?'':'disabled'} style="--stage-color:${stageColors[k]}" title="${e(name)}${first?' · 定位首次识别片段':' · 没有识别到此阶段'}"><span>${k+1}</span><b>${e(shortNames[k]||name)}</b></button>`;
  }).join('');
  const options=[[0,'全部原因'],[4,'输入不完整'],[1,'把握度较低'],[2,'模型意见分歧'],[32,'阶段证据不足'],[8,'无有效图像'],[16,'阶段切换附近'],[64,'阶段过渡待核查']]
    .filter(([bits])=>!bits||ranges.some(x=>x.bits&bits));
  return `<div class="stage-route" aria-label="识别阶段导航，点击定位，不表示任务完成">${buttons}</div>
    <section class="stage-live" aria-label="当前时刻的模型证据"><div class="stage-live-meta"><span>当前模型判断</span><time data-stage-live-time>0.0 s</time></div>
      <div class="stage-live-title"><strong class="warp-now" data-stage-live-name>—</strong><span><b data-stage-confidence>—</b><small>阶段把握度</small></span></div>
      <div class="stage-input-now" aria-label="当前采样输入"><span data-stage-input="head">头部 · —</span><span data-stage-input="right_wrist">右腕 · —</span>${r.stage_version>=2?'<span data-stage-input="state">关节 · —</span>':''}</div>
      <div class="stage-live-reasons" data-stage-live-reasons></div>
      <small class="stage-reason-detail" data-stage-reason-detail></small>

    </section>
    <p class="stage-outcome-note"><strong>最终结果待核验</strong> · 请查看画面确认香蕉是否入篮。</p>
    ${executionQualityHTML(panel)}
    <section class="stage-review-queue" aria-label="模型待复核片段"><div class="warp-heading"><h4>待复核片段 <span>${ranges.length}</span></h4></div>
      <div class="stage-review-tools"><select id="stage-reason-filter" aria-label="按模型复核原因筛选">${options.map(([bits,name])=>`<option value="${bits}" ${Number(panel.stageFilter)===bits?'selected':''}>${e(name)}</option>`).join('')}</select><button data-stage-review-nav="-1" aria-label="上一处模型待复核片段">← 上一处</button><button data-stage-review-nav="1" aria-label="下一处模型待复核片段">下一处 →</button></div>
      <div class="stage-review-list">${visible.map(x=>`<article class="stage-review-item" data-review-range="${x.id}"><button data-stage-review="${x.id}" class="stage-review-locate" title="定位片段起点"><b>${timeLabel(x.start_s)} – ${timeLabel(x.end_s)}</b><small>${e(x.reasons.join(' · ')||'模型提示复核')}</small></button><div class="stage-review-item-actions"><button data-stage-preview="${x.id}">回看</button><button data-stage-draft="${x.id}">填入审核范围</button></div></article>`).join('')||`<p class="stage-queue-empty">${ranges.length?'此原因下没有片段。':'当前模型没有触发复核提示，仍需核验最终结果。'}</p>`}</div>
      <p class="stage-draft-note">填入后可修改范围；点击“加入”并保存审核才会留下记录。</p></section>
    <details class="stage-evidence-details"><summary>详细证据与方法</summary>
      <section class="stage-probabilities"><h4>当前采样的五阶段概率</h4><p>展示同一采样的分类分布，用于比较候选阶段；不是任务成功概率。</p>${r.stage_names.map((name,k)=>`<div class="stage-prob-row" data-prob-row="${k}" style="--stage-color:${stageColors[k]}"><span>${e(name)}</span><i><em data-stage-prob-bar="${k}"></em></i><b data-stage-prob-value="${k}">—</b></div>`).join('')}<small data-stage-prob-note></small></section>
    <p>有效阶段覆盖 ${(s.coverage*100).toFixed(1)}%；${(s.review_fraction*100).toFixed(1)}% 采样触发复核提示。</p>
    <details class="stage-segments"><summary>全部阶段片段 <span>${r.stage_segments.length}</span></summary><div class="warp-candidates">${r.stage_segments.map((p,i)=>`<div class="warp-candidate" style="border-left-color:${stageColors[p.stage]}"><button data-warp-seek="${p.start_s}" class="warp-candidate-time">${p.start_s.toFixed(1)}–${p.end_s.toFixed(1)} s</button><span>${e(r.stage_names[p.stage])}<small>平均把握度 ${(p.mean_confidence*100).toFixed(0)}%</small></span><button class="small" data-stage-propose="${i}">填入审核范围</button></div>`).join('')||'<p>没有有效阶段，请检查相机数据。</p>'}</div></details>
    ${r.stage_version>=2?`<section class="stage-coverage"><h4>整段输入覆盖</h4><p class="stage-inputs">${e(stageInputSummary(r))}</p><p>输入不完整的采样已标为待复核。缺少一个相机或关节状态时可尝试估计；两个相机都无画面时不输出阶段。</p></section>`:''}
    <section class="warp-provenance"><h4>模型方法与评分依据</h4><p>${r.stage_version>=3?'双视角图像与关节位置 → 当前值及变化量 → 时序网络 → 阶段分类与进度估计。':r.stage_version>=2?'双视角图像与关节状态 → 时序网络 → 阶段分类与进度估计。':'双视角图像 → 阶段分类与进度估计。'}</p><p>训练标注尚未经过独立人工验收，模型未验证跨场景成功判别能力。高把握度也不能替代最终成功核验。</p><p>把握度低于 80%、模型意见分歧或输入不完整时提示复核。</p>${r.review_guard_enabled?'<p>“阶段证据不足”保留校准前的不确定信号。</p>':''}${r.boundary_review_enabled?'<p>阶段切换附近也会提示复核。</p>':''}${r.learned_boundary_review_enabled?'<p>辅助模型提示的“阶段过渡待核查”不代表精确切换时刻。</p>':''}<p>评分来自当前保存的模型输出，未重新推理。阶段进度不参与 WARP 动作块权重导出。</p><p>模型 SHA256：<code>${e(r.checkpoint_sha256)}</code></p><p>评分签名：<code>${e(r.signature)}</code></p></section></details>`;
}

export function updateStageNow(panel){
  const host=panel.host;if(!host?.isConnected)return;
  const r=panel.result,time=panel.time,phase=stageAt(r,time),evidence=stageEvidenceAt(r,time);
  const set=(selector,text)=>{const el=host.querySelector(selector);if(el&&el.textContent!==text)el.textContent=text;};
  set('[data-stage-live-time]',timeLabel(time));set('[data-stage-live-name]',phase?.name||'无有效阶段');
  set('[data-stage-confidence]',phase?`${(phase.confidence*100).toFixed(1)}%`:'—');
  const live=host.querySelector('.stage-live');if(live)live.dataset.review=String(!!evidence?.review);
  const reasons=evidence?.reasons||[];
  const reasonEl=host.querySelector('[data-stage-live-reasons]');
  if(reasonEl){const text=reasons.join(' / ')||(evidence?.review?'模型提示复核':phase?'当前未触发复核提示':'当前采样无可用阶段证据');
    if(reasonEl.textContent!==text)reasonEl.textContent=text;
    reasonEl.title=reasons.map(name=>reasonHelp[name]||name).join('\n');}
  set('[data-stage-reason-detail]',evidence?.review?(reasonHelp[reasons[0]]||'请结合当前画面核对阶段判断。'):'');
  const inputs={head:evidence?.cameras?.[0],right_wrist:evidence?.cameras?.[1],state:evidence?.state};
  const labels={head:'头部',right_wrist:'右腕',state:'关节'};
  for(const [key,value] of Object.entries(inputs)){
    const el=host.querySelector(`[data-stage-input="${key}"]`);if(!el)continue;
    el.dataset.valid=value===true?'yes':value===false?'no':'unknown';
    const text=`${labels[key]} · ${value===true?'有效':value===false?'缺失':'未提供'}`;if(el.textContent!==text)el.textContent=text;
  }
  host.querySelectorAll('[data-stage-jump]').forEach(el=>el.setAttribute('aria-current',Number(el.dataset.stageJump)===phase?.stage?'step':'false'));
  for(let k=0;k<r.stage_names.length;k++){
    const value=evidence?.probability?.[k],available=Number.isFinite(value);
    set(`[data-stage-prob-value="${k}"]`,available?`${(value*100).toFixed(1)}%`:'—');
    const bar=host.querySelector(`[data-stage-prob-bar="${k}"]`);if(bar)bar.style.width=available?`${value*100}%`:'0%';
  }
  set('[data-stage-prob-note]',evidence?.probability?`模型采样：${timeLabel(evidence.time)} · 仅使用当前及过去输入`:'当前没有可显示的完整分类分布。');
  host.querySelectorAll('[data-review-range]').forEach(el=>{
    const range=panel.reviewRanges.find(x=>x.id===el.dataset.reviewRange);
    el.classList.toggle('is-current',!!range&&range.start_s<=time&&time<range.end_s);
  });
  host.querySelectorAll('[data-stage-review-nav]').forEach(el=>el.disabled=!reviewTarget(panel.filteredReviewRanges(),time,Number(el.dataset.stageReviewNav)));
}
