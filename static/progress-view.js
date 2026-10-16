import {scoreAt,curvePath,candidateClip} from './progress-data.mjs';
import {stageAt,stageCurve,stageColors,preferredProgressModel,stageReviewIntervals,reviewTarget} from './stage-data.mjs';
import {stageResultHTML,updateStageNow,timeLabel} from './stage-view.js';
import {bindExecutionQuality} from './execution-quality.mjs';

const names={forward:'正向候选',stall:'停滞候选',regression:'回退候选'};
export class ProgressPanel {
  constructor({episode,api,escape,seek,preview,propose,open,toast}) {
    Object.assign(this,{episode,api,escape,seek,preview,propose,open,toast});
    this.models=[];this.selected='';this.filter='all';this.minDuration=1;this.stageFilter=0;this.reviewRanges=[];
    this.state='loading';this.result=null;this.time=0;this.generation=0;this.modelsGeneration=0;this.closed=false;this.detailOpen={};
    this.execution=null;this.executionError=null;this.executionDrafts={};this.executionGeneration=0;
    this.loadModels();
  }
  destroy(){this.closed=true;clearTimeout(this.timer);this.generation++;this.modelsGeneration++;this.host=null;}
  unmount(){this.rememberDetails();this.host=null;}
  mount(host){
    if(this.host===host&&host.querySelector('.warp-panel')){this.setTime(this.time);return;}
    this.host=host;this.render();
  }
  rememberDetails(){this.host?.querySelectorAll('.warp-panel details').forEach(el=>this.detailOpen[el.classList[0]]=el.open);}
  async loadModels(){
    const version=++this.modelsGeneration;
    try{
      if(this.episode.snapshot){
        const cached=await this.api(`/api/task-audit/curve?ep=${encodeURIComponent(this.episode.id)}`);
        if(this.closed||version!==this.modelsGeneration)return;
        this.result=cached.state==='ready'?cached:null;this.state=this.result?'ready':'unavailable';
        this.error=this.result?null:cached.reason;
        this.selected=cached.model_id||'';
        this.models=this.result?[{id:this.selected,kind:'warp_velocity',ready:true}]:[];
        this.render();return;
      }
      const data=await this.api('/api/progress/models');
      if(this.closed||version!==this.modelsGeneration)return;
      this.models=data.models;this.workflow=data.workflow;
      let saved=this.selected;try{saved ||= localStorage.getItem('robocurate-progress-model')||'';}catch{}
      this.selected=preferredProgressModel(this.models,saved);
      if(this.selected)await this.refresh();else{this.state='unavailable';this.render();}
    }catch(e){if(!this.closed&&version===this.modelsGeneration){this.error=e.message;this.state='failed';this.render();}}
  }
  async selectModel(id){
    this.execution=null;this.executionError=null;this.executionDrafts={};this.executionGeneration++;
    this.selected=id;this.result=null;this.reviewRanges=[];this.stageFilter=0;this.state='loading';this.error=null;
    try{localStorage.setItem('robocurate-progress-model',id);}catch{}
    this.render();await this.refresh();
  }
  async refresh(){
    if(this.episode.snapshot)return this.loadModels();
    clearTimeout(this.timer);const generation=++this.generation;
    try{
      if(this.episode.cache!=='ready'){this.state='needs_parse';this.render();return;}
      const data=await this.api(`/api/progress?ep=${encodeURIComponent(this.episode.id)}&model_id=${encodeURIComponent(this.selected)}`);
      if(this.closed||generation!==this.generation)return;
      this.state=data.state;this.result=data.result||null;this.job=data.job||null;this.error=null;
      this.reviewRanges=this.result?.kind==='stage_progress'?stageReviewIntervals(this.result,this.episode.duration_s):[];
      this.render();if(['queued','running'].includes(this.state))this.timer=setTimeout(()=>this.refresh(),2000);
      if(this.result?.kind==='stage_progress')this.loadExecution();
    }catch(e){if(!this.closed&&generation===this.generation){this.state='failed';this.error=e.message;this.render();}}
  }
  async loadExecution(){
    const generation=++this.executionGeneration,model=this.selected;
    try{
      const report=await this.api(`/api/execution-quality?ep=${encodeURIComponent(this.episode.id)}&model_id=${encodeURIComponent(model)}`);
      if(this.closed||generation!==this.executionGeneration||model!==this.selected)return;
      if(this.execution&&this.execution.signature!==report.signature)this.executionDrafts={};
      this.execution=report;this.executionError=null;this.render();
    }catch(error){if(!this.closed&&generation===this.executionGeneration){this.executionError=error.message;this.execution=null;this.render();}}
  }
  filteredReviewRanges(){return this.reviewRanges.filter(r=>!this.stageFilter||(r.bits&this.stageFilter));}
  chart(width=600,height=130){
    if(!this.result)return '';
    const accessible=`tabindex="0" role="slider" aria-label="${this.result.kind==='stage_progress'?'任务阶段与阶段进度估计':'相对进展速度'}，左右键定位视频" aria-valuemin="0" aria-valuemax="${this.episode.duration_s}" aria-valuenow="${this.time}"`;
    if(this.result.kind==='stage_progress'){
      const bands=(this.result.stage_segments||[]).map(s=>`<rect x="${s.start_s/this.episode.duration_s*width}" y="0" width="${(s.end_s-s.start_s)/this.episode.duration_s*width}" height="${height}" fill="${stageColors[s.stage]}" opacity=".15"><title>${this.escape(this.result.stage_names[s.stage])} · ${s.start_s.toFixed(1)}–${s.end_s.toFixed(1)} s</title></rect>`).join('');
      const reviews=this.reviewRanges.map(s=>`<rect class="stage-review-mark" x="${s.start_s/this.episode.duration_s*width}" y="${height-5}" width="${(s.end_s-s.start_s)/this.episode.duration_s*width}" height="5"><title>${s.start_s.toFixed(1)}–${s.end_s.toFixed(1)} s · ${this.escape(s.reasons.join(' / ')||'待复核')}</title></rect>`).join('');
      return `<svg class="warp-chart stage-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" ${accessible}>${bands}<path d="${stageCurve(this.result,this.episode.duration_s,width,height)}"/>${reviews}<line class="warp-playhead" x1="0" x2="0" y1="0" y2="${height}"/></svg>`;
    }
    const c=curvePath(this.result.times_s,this.result.velocity,this.episode.duration_s,width,height);
    return `<svg class="warp-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" ${accessible}><line x1="0" x2="${width}" y1="${c.standard}" y2="${c.standard}" class="warp-standard"/><line x1="0" x2="${width}" y1="${c.zero}" y2="${c.zero}" class="warp-zero"/><path d="${c.path}"/><line class="warp-playhead" x1="0" x2="0" y1="0" y2="${height}"/></svg>`;
  }
  modelControls(model,running){
    if(this.episode.snapshot)return '<p class="warp-domain">本任务缓存进展曲线，与回放同步。进展速度不参与质量评分。</p>';
    const e=this.escape,isStage=model?.kind==='stage_progress';
    const types=[['stage_progress','任务阶段'],['warp_velocity','WARP 相对进展']];
    const source=isStage?(model.stage_version>=2?'头部左目 + 右腕相机 + 身体与双手状态':'头部左目 + 右腕相机'):`${e(model?.camera||'')} · ${model?.view==='left'?'左目':'完整图像'}`;
    return `<details class="warp-settings" ${!this.result&&this.state!=='loading'?'open':''}><summary><span>分析设置</span><small>${e(model?.id||'正在读取…')}</small></summary><label class="field-label" for="warp-model">分析模型</label><select id="warp-model">${types.map(([kind,label])=>`<optgroup label="${label}">${this.models.filter(m=>(m.kind||'warp_velocity')===kind).map(m=>`<option value="${e(m.id)}" ${m.id===this.selected?'selected':''}>${e(m.label)}${m.ready?'':' · 未就绪'}</option>`).join('')}</optgroup>`).join('')}</select>
      ${model?`<p class="warp-domain">${e(model.name||model.id)}</p><div class="warp-source">${source}</div>`:''}
      <div class="warp-actions"><button class="primary" id="warp-start" ${!model?.ready||running||this.state==='needs_parse'||this.result?'disabled':''}>${this.result?'评分已就绪':isStage?'计算任务阶段':'计算相对进展'}</button><button id="warp-refresh">刷新状态</button>${running?'<button id="warp-cancel">取消评分</button>':''}</div></details>`;
  }
  renderTimeline(isStage,running){
    const timeline=document.querySelector('#progress-timeline');if(!timeline)return;
    timeline.classList.toggle('is-stage',isStage);
    const label=isStage?'任务阶段':'WARP 进展';
    timeline.innerHTML=`<div class="stage-timeline-heading"><span>${label}</span><span class="warp-now"></span></div>${this.result?this.chart(600,42):`<span class="muted">${running?'正在计算…':this.episode.snapshot?'尚无本任务进展结果':'在任务面板选择模型并运行分析'}</span>`}${this.result&&!isStage?'<div class="warp-axis"><span>0 s</span><span>虚线 1× · 实线 0</span><span>'+timeLabel(this.episode.duration_s)+'</span></div>':''}`;
    this.bindChart(timeline);
  }

  render(){
    if(this.closed)return;
    const e=this.escape,model=this.models.find(m=>m.id===this.selected),running=['queued','running'].includes(this.state),isStage=model?.kind==='stage_progress';
    this.renderTimeline(isStage,running);
    if(this.host?.isConnected){
      this.rememberDetails();const scroll=this.host.scrollTop;
      const status=this.result?'评分已就绪':running?'正在评分':this.state==='failed'?'评分失败':this.state==='needs_parse'?'待解析':this.state==='loading'?'正在读取':!model?.ready?'模型未就绪':'待计算';
      this.host.innerHTML=`<section class="warp-panel ${isStage?'is-stage':''}"><div class="warp-heading"><h3>${isStage?'香蕉搬运 · 任务阶段':'任务进展 · WARP-RM'}</h3><span class="warp-status">${status}</span></div><p class="warp-task-context">${isStage?'左桌取香蕉 → 搬到右桌 → 放入篮子。':'估计正向、停滞与回退，以模型标准演示为参照。速度不表示任务完成百分比。'}</p>
        ${!this.result?this.modelControls(model,running):''}${running?`<p role="status">${e(this.job?.message||'等待评分')} · ${this.job?.progress||0}%</p><progress max="100" value="${this.job?.progress||0}"></progress>`:''}
        ${this.error||['failed','interrupted'].includes(this.job?.state)?`<p class="warp-notice" role="status">${e(this.error||this.job.message)}</p>`:''}
        ${this.state==='needs_parse'?'<p class="warp-notice">请先完成记录解析，再运行模型分析。</p>':''}
        ${this.state==='unavailable'&&!this.episode.snapshot?'<div class="progress-empty"><b>尚未安装任务分析模型</b><p>可先使用质检与人工审核。安装模型后在分析设置中刷新即可。</p></div>':''}
        ${model&&!model.ready?`<p class="warp-notice">${e(['awaiting_access','access_rejected'].includes(this.workflow?.state)?this.workflow.message:'模型尚未就绪，请选择已就绪模型或完成安装后刷新。')}</p>`:''}
        ${this.result?.kind==='stage_progress'?stageResultHTML(this):this.result?this.warpResult():this.state==='absent'?'<div class="progress-empty"><b>这条记录尚未生成当前模型的分析</b><p>在上方点击计算，结果会与视频、时间轴同步显示。</p></div>':''}${this.result?this.modelControls(model,running):''}</section>`;
      for(const [cls,open] of Object.entries(this.detailOpen)){const el=this.host.querySelector(`details.${cls}`);if(el)el.open=open;}
      if(!this.episode.snapshot){
        if(!this.result&&this.state!=='loading')this.host.querySelector('.warp-settings').open=true;
        this.host.querySelector('#warp-model').onchange=ev=>this.selectModel(ev.target.value);
        this.host.querySelector('#warp-start').onclick=()=>this.start();this.host.querySelector('#warp-refresh').onclick=()=>this.loadModels();
      }
      const cancel=this.host.querySelector('#warp-cancel');if(cancel)cancel.onclick=async()=>{try{await this.api('/api/progress/cancel',{id:this.job.id});await this.refresh();}catch(err){this.toast(err.message,true);}};
      this.host.querySelectorAll('[data-warp-seek]').forEach(b=>b.onclick=()=>this.seek(Number(b.dataset.warpSeek)));
      this.host.querySelectorAll('[data-warp-propose]').forEach(b=>b.onclick=()=>{const s=this.result.summary.suggestions.find(s=>s.id===b.dataset.warpPropose);const clip=candidateClip(s,this.episode.duration_s);if(clip)this.propose(clip);});
      this.host.querySelectorAll('[data-stage-propose]').forEach(b=>b.onclick=()=>{const s=this.result.stage_segments[Number(b.dataset.stagePropose)];if(s)this.propose({start:s.start_s,end:s.end_s,label:'阶段待复核：'+this.result.stage_names[s.stage]});});
      this.host.querySelectorAll('[data-warp-filter]').forEach(b=>b.onclick=()=>{this.filter=b.dataset.warpFilter;this.render();this.host.querySelector(`[data-warp-filter="${this.filter}"]`)?.focus({preventScroll:true});});
      const duration=this.host.querySelector('#warp-min-duration');if(duration)duration.onchange=ev=>{this.minDuration=Number(ev.target.value);this.render();};
      const stageFilter=this.host.querySelector('#stage-reason-filter');if(stageFilter)stageFilter.onchange=ev=>{this.stageFilter=Number(ev.target.value);this.render();this.host.querySelector('#stage-reason-filter')?.focus({preventScroll:true});};
      this.bindChart(this.host);this.bindStage(this.host);bindExecutionQuality(this);this.host.scrollTop=scroll;
    }
    this.setTime(this.time);
  }
  warpResult(){
    if(this.episode.snapshot){
      const r=this.result,e=this.escape;
      return `<p class="warp-readout">当前 <b class="warp-now">—</b> · 点击曲线定位缓存画面</p>${this.chart()}<p>以同域演示为参照的相对进展速度；不表示完成百分比，也不证明任务成功。</p><details class="warp-provenance"><summary>模型依据</summary><p>${e(r.model_id)}</p><p>模型 SHA256：<code>${e(r.checkpoint_sha256)}</code></p><p>冻结 DINOv2 + 时序 Transformer；公开权重替代版本，非论文原版 DINOv3。</p></details>`;
    }
    const r=this.result,s=r.summary,e=this.escape,items=s.suggestions.filter(x=>(this.filter==='all'||x.kind===this.filter)&&x.end_s-x.start_s>=this.minDuration);
    return `<div class="warp-metrics"><div><strong>${(s.coverage*100).toFixed(1)}%</strong><span>评分覆盖</span></div><div><strong>${s.mean_velocity===null?'—':s.mean_velocity.toFixed(2)+'×'}</strong><span>平均进展速度</span></div><div><strong>${r.windows}</strong><span>观察窗口</span></div></div><p class="warp-readout">当前 <b class="warp-now">—</b> · 点击曲线定位视频</p>${r.shortened_windows?`<p class="warp-notice">${r.shortened_windows} 个窗口缩短至 ${r.span_s_min.toFixed(2)}–${r.span_s_max.toFixed(2)} 秒，已按实际间隔校准速度。</p>`:''}<div class="warp-heading"><h4>片段候选</h4><span class="muted">需结合视频复核</span></div>${this.filterControls(s)}<div class="warp-candidates">${items.slice(0,80).map(x=>`<div class="warp-candidate ${e(x.kind)}"><button data-warp-seek="${x.start_s}" class="warp-candidate-time">${x.start_s.toFixed(2)}–${x.end_s.toFixed(2)} s</button><span>${names[x.kind]}<small>${x.mean_velocity.toFixed(2)}×</small></span><button class="small" data-warp-propose="${e(x.id)}">填入审核范围</button></div>`).join('')||'<p class="muted">此类别下没有持续 '+this.minDuration.toFixed(1)+' 秒以上的候选。</p>'}</div><details class="warp-provenance"><summary>评分依据</summary><p>模型 SHA256：<code>${e(r.checkpoint_sha256)}</code></p><p>评分签名：<code>${e(r.signature)}</code></p><p>提取 ${r.feature_valid_count}/${r.frame_count} 个有效图像特征。缺帧与窗口未覆盖区间保留为空白。</p><p>候选死区 ±${s.deadband}×；候选仅填入编辑范围，保存由审核人员完成。</p></details>`;
  }
  filterControls(summary){
    const labels={all:'全部',forward:'正向',stall:'停滞',regression:'回退'};
    return `<div class="warp-filters" role="group" aria-label="按进展类别筛选候选">${Object.entries(labels).map(([kind,label])=>{
      const count=summary.suggestions.filter(s=>(kind==='all'||s.kind===kind)&&s.end_s-s.start_s>=this.minDuration).length;
      return `<button data-warp-filter="${kind}" aria-pressed="${this.filter===kind}">${label} <span>${count}</span></button>`;
    }).join('')}</div><label class="warp-duration">最短持续时间 <select id="warp-min-duration">${[.4,1,2].map(v=>`<option value="${v}" ${v===this.minDuration?'selected':''}>${v} 秒</option>`).join('')}</select></label>`;
  }
  bindStage(host){
    host.querySelectorAll('[data-stage-jump]').forEach(b=>b.onclick=()=>{const s=this.result?.stage_segments?.find(s=>s.stage===Number(b.dataset.stageJump));if(s)this.seek(s.start_s);});
    host.querySelectorAll('[data-stage-review-nav]').forEach(b=>b.onclick=()=>{const r=reviewTarget(this.filteredReviewRanges(),this.time,Number(b.dataset.stageReviewNav));if(r)this.seek(r.start_s);});
    for(const [attr,action] of [['data-stage-review',r=>this.seek(r.start_s)],['data-stage-preview',r=>this.preview?this.preview(Math.max(0,r.start_s-1),Math.min(this.episode.duration_s,r.end_s+1)):this.seek(r.start_s)],['data-stage-draft',r=>this.propose({start:r.start_s,end:r.end_s,label:'阶段待复核：'+(r.reasons.join(' / ')||'模型提示')})]]){
      host.querySelectorAll(`[${attr}]`).forEach(b=>b.onclick=()=>{const r=this.reviewRanges.find(x=>x.id===b.getAttribute(attr));if(r)action(r);});
    }
  }
  bindChart(host){host.querySelectorAll('.warp-chart').forEach(svg=>{
    svg.onclick=ev=>{const rect=svg.getBoundingClientRect();this.seek(Math.max(0,Math.min(1,(ev.clientX-rect.left)/rect.width))*this.episode.duration_s);};
    svg.onkeydown=ev=>{let t=this.time;const step=ev.shiftKey?5:.5;
      if(ev.key==='ArrowLeft')t-=step;else if(ev.key==='ArrowRight')t+=step;else if(ev.key==='Home')t=0;else if(ev.key==='End')t=this.episode.duration_s;else return;
      ev.preventDefault();ev.stopPropagation();this.seek(Math.max(0,Math.min(t,this.episode.duration_s)));
    };
  });}
  setTime(time){
    this.time=time;const isStage=this.result?.kind==='stage_progress',phase=isStage?stageAt(this.result,time):null;
    const value=this.result&&!isStage?scoreAt(this.result.times_s,this.result.velocity,time):null;
    for(const host of [this.host,document.querySelector('#progress-timeline')]){
      if(!host?.isConnected)continue;
      host.querySelectorAll('.warp-now:not([data-stage-live-name])').forEach(el=>el.textContent=isStage?(phase?`${phase.name} · ${(phase.confidence*100).toFixed(0)}%${phase.review?' · 待复核':''}`:'无有效阶段'):(value===null?'无有效评分':`${value.toFixed(2)}×`));
      host.querySelectorAll('.warp-playhead').forEach(el=>{const width=el.ownerSVGElement.viewBox.baseVal.width;el.setAttribute('x1',time/this.episode.duration_s*width);el.setAttribute('x2',time/this.episode.duration_s*width);});
      host.querySelectorAll('.warp-chart').forEach(el=>{el.setAttribute('aria-valuenow',String(time));el.setAttribute('aria-valuetext',`${timeLabel(time)}${phase?' · '+phase.name:''}`);});
      host.querySelectorAll('[data-stage-review-nav]').forEach(el=>el.disabled=!reviewTarget(this.filteredReviewRanges(),time,Number(el.dataset.stageReviewNav)));
    }
    if(isStage)updateStageNow(this);
  }
  async start(){try{await this.api('/api/progress/jobs',{ep:this.episode.id,model_id:this.selected});await this.refresh();}catch(e){this.toast(e.message,true);}}
}

export async function mountProgressExport(host,api,escape,onChange){
  const data=await api('/api/progress/models');
  if(!host.isConnected)return;
  host.innerHTML=`<details class="warp-export"><summary>任务进展权重（可选）</summary><label><input type="checkbox" id="export-warp"> 为训练包附加 WARP 动作块权重</label><p class="muted">按动作块末帧速度筛选，保留完整片段与质检掩码。需先为所有选中记录完成评分。</p><label class="field-label" for="export-warp-model">模型</label><select id="export-warp-model">${data.models.filter(m=>m.supports_weights!==false).map(m=>`<option value="${escape(m.id)}">${escape(m.label)}</option>`).join('')}</select><p class="warp-export-domain warp-domain"></p><div class="warp-export-fields"><label>速度阈值<input id="export-warp-threshold" type="number" min="0" max="100" step="0.05" value="1"></label><label>动作块帧数<input id="export-warp-horizon" type="number" min="1" max="10000" step="1" value="30"></label><label>权重模式<select id="export-warp-mode"><option value="continuous">末帧速度</option><option value="binary">保留为 1</option></select></label></div><p class="muted">阈值采用严格大于；片段尾部不补齐。训练时使用导出的 sample_weight。</p></details>`;
  const update=()=>{host.querySelector('.warp-export-domain').textContent=data.models.find(m=>m.id===host.querySelector('#export-warp-model').value)?.name||'尚未安装进展模型';onChange();};
  host.addEventListener('change',update);update();
}

export function progressExportOptions(){
  if(!document.querySelector('#export-warp')?.checked || document.querySelector('input[name="export-kind"]:checked')?.value!=='dataset')return null;
  const value=id=>document.getElementById(id).value;
  return {model_id:value('export-warp-model'),threshold:Number(value('export-warp-threshold')),horizon:Number(value('export-warp-horizon')),mode:value('export-warp-mode')};
}
