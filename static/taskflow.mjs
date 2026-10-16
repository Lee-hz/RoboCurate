import {FeedbackPanel,relatedRequests} from './feedback-panel.mjs';
import {AuditTools} from './audit-tools.mjs';
import {recordingAudits,preferredRun,recordNavigation,REVIEW_MODEL} from './record-audit.mjs';
import {FramePlayer,adjacentFrame} from './playback.mjs';
import {advancePlayback} from './playback-clock.mjs';
const labels={completed:'已完成',not_completed:'未完成',uncertain:'证据不足'};
const cameraNames={head:'头部',right_wrist:'右腕',left_wrist:'左腕',ego_view:'仿真视角',video:'视频'};
const modeName=mode=>mode==='state'?'画面＋机器人反馈':'纯视觉对照';
const sec=n=>Number(n).toFixed(1)+'s';
const icon=name=>`<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><use href="/workspace-icons.svg#${name}"/></svg>`;

export function reviewRange(duration,mode,start,end){
  if(!Number.isFinite(duration)||duration<=0)throw Error('请先选择有效的待审录像。');
  if(mode==='full')return {start_s:0,end_s:duration};
  if(mode!=='custom'||String(start).trim()===''||String(end).trim()==='')throw Error('请填写检查起点和终点。');
  const a=Number(start),b=Number(end);
  if(!Number.isFinite(a)||!Number.isFinite(b)||a<0||b>duration||a>=b||b-a<.2)throw Error('检查范围需在录像内，终点大于起点，且至少覆盖 0.2 秒。');
  return {start_s:a,end_s:b};
}

export function latestReviewJob(jobs=[]){
  const reviews=jobs.filter(j=>j.kind==='review');
  return reviews.find(j=>['queued','running'].includes(j.state))||reviews[0]||null;
}
export function jobElapsed(job,now=Date.now()){
  const seconds=Math.max(0,Math.floor((now-Date.parse(job.created_at))/1000));
  return Number.isFinite(seconds)?`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`:'';
}

export class Taskflow {
  constructor(root,api,escape){this.root=root;this.api=api;this.e=escape;this.alive=true;this.busy=false;this.run=null;this.template=null;this.segmentIndex=0;this.playerEpoch=0;this.detailTab='criteria';this.segmentFilter='all';this.reviewDrafts=new Map();}
  q(s){return this.root.querySelector(s);}
  async mount(initialRun=null,context={}){
    this.context=context;this.recording=context.recording||null;this.configurationOnly=Boolean(context.configurationOnly);this.reviewDrafts=new Map(context.savedState?.drafts||[]);
    this.pinRun=Boolean(initialRun);if(this.recording&&!this.configurationOnly)this.audit=new AuditTools(this,this.recording);
    this.root.classList.add('tf-root');if(this.configurationOnly)this.root.classList.add('tf-config-only');
    this.root.innerHTML=`<div class="tf-page">${this.recording?recordNavigation(this.recording,'stages',this.e):''}
      <header class="tf-header"><div class="tf-heading"><h1>${this.recording?this.e(this.recording.episode_id||this.recording.name):'真机数据审核'}</h1></div><div class="tf-header-actions">${this.recording?'':`<button data-tf="setup" data-tab="source">${icon('import')} 导入数据</button>`}</div></header>
      <div id="tf-message" role="status" aria-live="polite"></div><section id="tf-jobs" aria-live="polite"></section>
      <section class="tf-results" aria-label="逐段审核结果"><div class="tf-workbar"><div class="tf-run-picker"><label for="tf-runs">${this.recording?'本条分析记录':'审核记录'}</label><select id="tf-runs" aria-label="选择审核结果"></select></div><div class="tf-inline"><button data-tf="setup" data-tab="review" title="查看范本、输入与分析设置">${icon('sliders')} MiniMax 审核</button><button data-tf="export" id="tf-export" disabled>${icon('export')} 导出结果</button></div></div><div id="tf-result"><div class="tf-empty">${icon('camera')}<h2>${this.recording?'这条记录还没有阶段审核':'从一段真机录像开始'}</h2><p>${this.recording?'录像已选定。选择任务范本，检查每个阶段的目标与重复尝试。':'导入采集记录，选择任务范本，即可查看阶段切分与目标判断。'}</p><button class="tf-primary" data-tf="setup" data-tab="${this.recording?'review':'source'}">${icon('plus')} ${this.recording?'选择范本并设置审核':'准备审核数据'}</button></div></div></section>
      <dialog id="tf-setup-dialog" class="tf-dialog" aria-labelledby="tf-setup-title"><div class="tf-dialog-header"><div><h2 id="tf-setup-title">准备任务审核</h2><p>选择数据与范本，然后提交分析。</p></div><button class="tf-icon-button" data-tf="close-setup" aria-label="关闭审核设置">${icon('close')}</button></div>
      <div class="tf-setup-tabs" role="tablist" aria-label="审核准备"><button role="tab" id="tf-tab-source" aria-controls="tf-setup-source" data-tf="setup-tab" data-tab="source" ${this.recording?'hidden':''}>导入数据</button><button role="tab" id="tf-tab-reference" aria-controls="tf-setup-reference" data-tf="setup-tab" data-tab="reference">任务范本</button><button role="tab" id="tf-tab-review" aria-controls="tf-setup-review" data-tf="setup-tab" data-tab="review">开始审核</button></div>
      <div class="tf-dialog-body"><div id="tf-setup-message" role="status" aria-live="polite"></div><section class="tf-setup">
      <div id="tf-setup-source" role="tabpanel" aria-labelledby="tf-tab-source" class="tf-setup-panel"><h3>使用本机采集记录</h3><p class="tf-note">优先使用 MCAP，保留相机、关节和手部反馈。</p><label>采集记录<select id="tf-record"><option value="">正在读取记录…</option></select></label><button class="tf-primary" data-tf="register-record">加入审核数据</button><div class="tf-divider">导入独立视频</div><div class="tf-inline"><label class="tf-file">${icon('import')} 上传视频<input type="file" id="tf-upload" accept="video/*,.mkv,.avi"></label><span class="tf-muted">最大 1 GB · 视频仅提供画面</span></div><details><summary>使用本机视频路径</summary><div class="tf-inline"><input id="tf-path" placeholder="/home/…/demo.mp4" aria-label="本机视频路径"><button data-tf="register-path">导入</button></div></details></div>
      <div id="tf-setup-reference" role="tabpanel" aria-labelledby="tf-tab-reference" class="tf-setup-panel" hidden><h3>任务范本</h3><label>已有范本<select id="tf-manage-template"></select></label><button class="tf-text-button" data-tf="manage-template">查看与编辑完成条件 ${icon('arrow-right')}</button><div class="tf-divider">从录像建立新范本</div><p class="tf-note">已有范本可直接开始审核。新任务可从录像中生成阶段与完成条件。</p><label>范本录像<select id="tf-reference"></select></label><label>任务要求 <span class="tf-muted">可选</span><textarea id="tf-instruction" maxlength="2000" placeholder="例如：物体入篮后，手臂收回并离开桌子"></textarea></label><button class="tf-primary" data-tf="reference">解析范本</button><p class="tf-note">使用下方分析方式。范本中的失败尝试也会保留。</p></div>
      <div id="tf-setup-review" role="tabpanel" aria-labelledby="tf-tab-review" class="tf-setup-panel" hidden><h3>审核同类任务</h3><p class="tf-note">段数与顺序由待审录像决定，支持多次尝试和动作回退。</p><label>任务范本<select id="tf-template"></select></label><button class="tf-text-button" data-tf="edit-template">查看与编辑完成条件 ${icon('arrow-right')}</button><label>待审录像<select id="tf-target"></select></label><fieldset class="tf-review-range"><legend>检查区间</legend><label>范围<select id="tf-range-mode"><option value="full">整段录像</option><option value="custom">指定时间区间</option></select></label><div id="tf-range-fields" class="tf-range-fields" hidden><label>起点（秒）<input id="tf-range-start" type="number" min="0" step="any" aria-describedby="tf-range-summary"></label><label>终点（秒）<input id="tf-range-end" type="number" min="0" step="any" aria-describedby="tf-range-summary"></label></div><button class="tf-text-button" data-tf="reuse-range" id="tf-reuse-range" disabled>沿用当前结果的录像与区间</button><p id="tf-range-summary" class="tf-note" role="status" aria-live="polite"></p><p class="tf-note">只判断所选区间；可能读取区间前后的画面核对结果，其余时间不计为已审核。切换分析方式会保留区间。</p></fieldset><button class="tf-primary" data-tf="review">${icon('play')} 开始自动审核</button></div></section>
      <div class="tf-input-settings"><p class="tf-model-policy">审核模型：<button type="button" id="tf-provider" class="tf-provider tf-text-button" data-minimax-access>MiniMax 接入</button></p><label>分析方式 · 范本与待审录像<select id="tf-mode"><option value="state">画面＋机器人反馈（真机优先）</option><option value="visual">纯视觉对照</option></select></label><p class="tf-note">抽取画面与所选反馈摘要发送至公司模型。原始录像保留在本机。</p></div><section id="tf-state-preview" class="tf-state-preview"></section><details class="tf-job-history"><summary>分析历史</summary><div id="tf-job-history"></div></details></div></dialog>
      <dialog id="tf-spec-dialog" class="tf-dialog tf-wide-dialog" aria-label="编辑任务定义"><div id="tf-spec-message" role="status"></div><section id="tf-spec"></section></dialog>
      <dialog id="tf-boundary-dialog" class="tf-dialog tf-wide-dialog" aria-label="修订分段"><div id="tf-boundary-message" role="status"></div><div id="tf-boundaries"></div></dialog>
    </div>`;
    this.click=e=>{const b=e.target.closest('[data-tf]');if(b&&this.root.contains(b))this.action(b).catch(err=>this.message(err.message,true));};
    this.change=e=>{if(e.target.id==='tf-input-request')this.renderInputRequest(e.target.value);if(e.target.id==='tf-manage-template')this.q('#tf-template').value=e.target.value;if(e.target.id==='tf-target')this.syncReviewRange();if(e.target.id==='tf-range-mode')this.updateRangeSummary();if(['tf-target','tf-reference','tf-mode'].includes(e.target.id))this.refreshSetupPreview();if(e.target.id==='tf-camera')this.switchCamera(e.target.value);if(e.target.id==='tf-speed'&&this.q('#tf-video'))this.q('#tf-video').playbackRate=Number(e.target.value);if(e.target.id==='tf-upload')this.upload(e.target.files[0]);if(e.target.id==='tf-runs'&&e.target.value)this.loadRun(e.target.value).catch(err=>this.message(err.message,true));};
    this.root.addEventListener('click',this.click);this.root.addEventListener('change',this.change);
    this.input=e=>{if(['tf-range-start','tf-range-end'].includes(e.target.id))this.updateRangeSummary();};this.root.addEventListener('input',this.input);
    this.keydown=ev=>{if(!ev.target.closest('input,textarea,select,button,summary,[contenteditable=true],dialog')&&this.run){if(ev.code==='Space'){ev.preventDefault();this.play();return;}if(['ArrowLeft','ArrowRight'].includes(ev.key)){ev.preventDefault();this.stepFrame(ev.key==='ArrowRight'?1:-1);return;}}const tab=ev.target.closest('[role="tab"]');if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(ev.key))return;ev.preventDefault();const tabs=[...tab.parentElement.querySelectorAll('[role="tab"]')];let i=tabs.indexOf(tab);i=ev.key==='Home'?0:ev.key==='End'?tabs.length-1:(i+(ev.key==='ArrowRight'?1:tabs.length-1))%tabs.length;tabs[i].focus();tabs[i].click();};
    this.root.addEventListener('keydown',this.keydown);
    this.root.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('cancel',()=>{this.editing=false;}));
    this.setSetupTab(this.configurationOnly?'reference':'review');
    const [rawOverview,catalog]=await Promise.all([this.api('/api/taskflow'),this.api('/api/catalog')]);if(!this.alive)return;
    this.catalog=catalog.episodes.filter(r=>Object.keys(r.cameras||{}).length);
    this.q('#tf-record').innerHTML='<option value="">请选择记录</option>'+this.catalog.map(r=>`<option value="${this.e(r.id)}">${this.e(r.domain==='sim'?'仿真':r.domain==='real'?'真机':'MCAP')} · ${this.e(r.episode_id||r.name||r.id)} · ${this.e(r.id)}</option>`).join('');
    const overview=this.contextualOverview(rawOverview);this.updateOverview(overview);
    const saved=context.savedState,remembered=overview.runs.find(r=>r.id===saved?.runId);
    if(initialRun)await this.loadRun(initialRun);else if(!this.configurationOnly&&overview.runs.length)await this.loadRun(remembered?.id||preferredRun(overview.runs).id);
    if(this.run&&this.run.id===saved?.runId){this.segmentIndex=Math.max(0,this.run.result.segments.findIndex(s=>s.id===saved.segmentId));this.detailTab=['criteria','inputs','manual'].includes(saved.detailTab)?saved.detailTab:'criteria';this.segmentFilter=saved.filter;this.showSegment();this.applySegmentFilter();if(saved.camera)this.switchCamera(saved.camera);if(saved.view)this.audit?.setMode(saved.view);this.seek(saved.time||0);}
    if(!this.run&&this.recording&&!this.configurationOnly)this.renderUnreviewed();
    if(!this.run)await this.previewState(this.q('#tf-target').value);
    if(this.configurationOnly)this.openSetup('reference');
    this.timer=setInterval(()=>this.refresh().catch(e=>this.message(e.message,true)),3500);
  }
  viewState(){this.captureReviewDraft();return {runId:this.run?.id,segmentId:this.run?.result.segments[this.segmentIndex]?.id,detailTab:this.detailTab,filter:this.segmentFilter,time:this.time,camera:this.q('#tf-camera')?.value,view:this.audit?.mode,drafts:[...this.reviewDrafts]};}
  contextualOverview(data){
    if(!this.recording)return data;
    const related=recordingAudits(data,this.recording.id),assets=[...data.assets];
    if(!related.assets.length){const asset={id:'pending-recording',name:this.recording.episode_id||this.recording.name,duration_s:this.recording.duration_s,source:{kind:'recording',id:this.recording.id,snapshot:Boolean(this.recording.snapshot),camera:Object.keys(this.recording.cameras||{})[0]||'head'}};assets.push(asset);related.assets.push(asset);}
    this.targetAssets=related.assets;
    return {...data,assets,runs:related.runs,jobs:related.jobs};
  }
  message(text,error=false){if(!this.alive)return;for(const id of ['#tf-message','#tf-setup-message','#tf-spec-message','#tf-boundary-message']){const box=this.q(id);box.className=text?'tf-message'+(error?' tf-error':''):'';box.textContent=text;}}
  setSetupTab(tab){this.setupTab=tab;this.root.querySelectorAll('[data-tf="setup-tab"]').forEach(b=>{const active=b.dataset.tab===tab;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});for(const name of ['source','reference','review'])this.q('#tf-setup-'+name).hidden=name!==tab;this.refreshSetupPreview();}
  openSetup(tab='review'){this.stop();this.message('');this.setSetupTab(tab);this.q('#tf-setup-dialog').showModal();}
  refreshSetupPreview(){const id=this.q(this.setupTab==='reference'?'#tf-reference':'#tf-target')?.value;this.previewState(id).catch(err=>this.message(err.message,true));}
  syncReviewRange(scope=null){
    const id=this.q('#tf-target').value,asset=this.assets?.find(a=>a.id===id);
    if(id!==this.rangeAssetId||scope){
      this.rangeAssetId=id;const start=scope?.start_s??0,end=scope?.end_s??asset?.duration_s??'';
      this.q('#tf-range-mode').value=scope&&(start!==0||end!==asset?.duration_s)?'custom':'full';
      this.q('#tf-range-start').value=start;this.q('#tf-range-end').value=end;
    }
    for(const selector of ['#tf-range-start','#tf-range-end'])this.q(selector).max=asset?.duration_s??0;
    this.q('#tf-reuse-range').disabled=!this.run?.id;this.updateRangeSummary();
  }
  selectedReviewRange(){const asset=this.assets?.find(a=>a.id===this.q('#tf-target').value);return reviewRange(asset?.duration_s,this.q('#tf-range-mode').value,this.q('#tf-range-start').value,this.q('#tf-range-end').value);}
  updateRangeSummary(){
    const custom=this.q('#tf-range-mode').value==='custom';this.q('#tf-range-fields').hidden=!custom;
    for(const selector of ['#tf-range-start','#tf-range-end'])this.q(selector).disabled=!custom;
    const box=this.q('#tf-range-summary');
    try{const scope=this.selectedReviewRange();box.textContent=`将检查 ${scope.start_s}–${scope.end_s} 秒，共 ${(scope.end_s-scope.start_s).toFixed(3)} 秒。提交后调用公司模型。`;box.className='tf-note';}
    catch(err){box.textContent=err.message;box.className='tf-warning';}
  }
  setDetailTab(tab){const changed=this.detailTab!==tab;this.detailTab=tab;if(changed&&this.q('.tf-detail-body'))this.q('.tf-detail-body').scrollTop=0;this.root.querySelectorAll('[data-tf="detail-tab"]').forEach(b=>{const active=b.dataset.tab===tab;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});this.root.querySelectorAll('[data-detail-panel]').forEach(panel=>panel.hidden=panel.dataset.detailPanel!==tab);}
  applySegmentFilter(){let shown=0;this.root.querySelectorAll('.tf-segment-row').forEach(b=>{b.hidden=this.segmentFilter!=='all'&&b.dataset.completion!==this.segmentFilter;if(!b.hidden)shown++;});this.root.querySelectorAll('[data-tf="filter-segments"]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.filter===this.segmentFilter)));const empty=this.q('#tf-segment-empty');if(empty)empty.hidden=shown>0;}

  options(id,rows,placeholder,label){const el=this.q(id),old=el.value,html=`<option value="">${placeholder}</option>`+rows.map(r=>`<option value="${this.e(r.id)}">${this.e(label(r))}</option>`).join('');if(el.dataset.optionsHtml===html)return;el.dataset.optionsHtml=html;el.innerHTML=html;if(rows.some(r=>r.id===old))el.value=old;else if(rows.length)el.value=rows[0].id;}
  updateOverview(data){
    this.overview=data;this.assets=data.assets;
    const provider=this.q('#tf-provider');provider.textContent=`${data.provider.model||'视觉模型'} · ${data.provider.tested?'已连接':data.provider.configured?'待验证':'未配置'}`;provider.dataset.connected=String(Boolean(data.provider.tested));provider.title=data.provider.label;
    this.options('#tf-reference',data.assets.filter(a=>a.id!=='pending-recording'),'先添加一段范本',r=>`${r.name} · ${sec(r.duration_s)}`);
    this.options('#tf-target',this.targetAssets||data.assets,'先添加待审录像',r=>`${r.name} · ${sec(r.duration_s)}`);
    this.q('#tf-target').disabled=Boolean(this.recording);
    this.syncReviewRange();
    this.options('#tf-template',data.templates,'先解析任务范本',r=>`${r.name} · ${r.stage_count} 类阶段 · v${r.revision}`);
    this.options('#tf-manage-template',data.templates,'暂无范本',r=>`${r.name} · v${r.revision}`);
    this.options('#tf-runs',data.runs,'暂无审核结果',r=>`${r.model!==REVIEW_MODEL?'历史 · ':''}${r.model||'模型未标注'} · ${modeName(r.analysis_mode)} · ${r.summary.segment_count} 段 · ${new Date(r.created_at).toLocaleString('zh-CN',{hour12:false})}`);
    if(this.run?.id)this.q('#tf-runs').value=this.run.id;
    const jobHtml=j=>{
      const active=['queued','running'].includes(j.state),failed=['failed','interrupted'].includes(j.state);
      const title=j.kind==='reference'?'范本解析':active?'MiniMax 分析中':failed?'分析未完成':j.state==='cancelled'?'分析已取消':'分析完成';
      return `<div class="tf-job" data-state="${this.e(j.state)}"><div><b>${title}${active?`<small>${j.state==='queued'?'已等待':'已用时'} ${jobElapsed(j)}</small>`:''}</b><span>${this.e(j.message)}</span></div>${active?`<progress max="100" value="${Number(j.progress)}" aria-label="分析步骤进度"></progress><button data-tf="cancel" data-id="${j.id}" ${j.cancel_requested?'disabled':''}>${j.cancel_requested?'取消中':'取消'}</button>`:j.result_id?`<button data-tf="open-run" data-id="${j.result_id}">查看结果</button>`:j.kind==='review'?`<button data-tf="retry-job" data-id="${j.id}">重试审核</button>`:''}</div>`;
    };
    const active=data.jobs.filter(j=>['queued','running'].includes(j.state));
    const latest=latestReviewJob(data.jobs),lastRun=data.runs[0];
    const recoverable=latest&&['failed','cancelled','interrupted'].includes(latest.state)&&(!lastRun||latest.created_at>lastRun.created_at);
    const shown=active.length?active:recoverable?[latest]:[];
    this.q('#tf-jobs').innerHTML=shown.map(jobHtml).join('');
    this.q('#tf-job-history').innerHTML=data.jobs.length?data.jobs.map(jobHtml).join(''):'<p class="tf-note">暂无分析记录</p>';
    const submit=this.q('[data-tf="review"]');if(submit)submit.disabled=active.some(j=>j.kind==='review'&&j.asset_id===this.q('#tf-target').value);
    const workbar=this.q('.tf-workbar');if(workbar)workbar.hidden=Boolean(this.recording&&!data.runs.length);
    const empty=this.q('#tf-review-status');if(empty)empty.hidden=shown.length>0;
  }

  async refresh(){
    if(!this.alive||this.refreshing)return;this.refreshing=true;
    try{const raw=await this.api('/api/taskflow');if(!this.alive)return;const data=this.contextualOverview(raw);
      const before=new Set(this.overview?.runs.map(r=>r.id)),jobs=new Map(this.overview?.jobs.map(j=>[j.id,j.state]));
      this.updateOverview(data);
      const finished=data.jobs.find(j=>['queued','running'].includes(jobs.get(j.id))&&!['queued','running'].includes(j.state));
      if(finished)this.message(finished.state==='completed'?'分析完成，已载入阶段结果。':'');
      const fresh=data.runs.find(r=>!before.has(r.id))||(!this.run?.id?preferredRun(data.runs):null);if(fresh&&!this.configurationOnly&&!this.editing&&!this.pinRun)await this.loadRun(fresh.id);
    }finally{this.refreshing=false;}
  }
  async action(b){
    const action=b.dataset.tf;
    if(action==='manage-template'){this.q('#tf-template').value=this.q('#tf-manage-template').value;return this.action({dataset:{tf:'edit-template'}});}
    if(action==='setup'){this.openSetup(b.dataset.tab);return;}
    if(action==='retry-job'){
      const job=this.overview.jobs.find(j=>j.id===b.dataset.id);if(!job)throw Error('未找到这次分析记录，请刷新后重试。');
      this.openSetup('review');this.q('#tf-target').value=job.asset_id;this.q('#tf-template').value=job.template_id;
      this.q('#tf-mode').value=job.analysis_mode||'visual';this.q('#tf-instruction').value=job.instruction||'';
      this.syncReviewRange(job.analysis_range);this.refreshSetupPreview();
      this.message('已恢复上次的范本、分析方式和检查区间。确认后开始重试。');return;
    }
    if(action==='reuse-range'){if(this.run){this.q('#tf-target').value=this.run.asset_id;this.syncReviewRange(this.run.result.analysis_range||{start_s:0,end_s:this.assets.find(a=>a.id===this.run.asset_id).duration_s});this.refreshSetupPreview();}return;}
    if(action==='close-setup'){this.q('#tf-setup-dialog').close();return;}
    if(action==='setup-tab'){this.setSetupTab(b.dataset.tab);return;}
    if(action==='show-inputs'){this.setDetailTab('inputs');return;}
    if(action==='detail-tab'){this.setDetailTab(b.dataset.tab);return;}
    if(action==='filter-segments'){this.segmentFilter=b.dataset.filter;this.applySegmentFilter();return;}
    if(action==='neighbor'){const i=this.segmentIndex+Number(b.dataset.offset);if(i>=0&&i<this.run.result.segments.length){this.stop();this.segmentIndex=i;this.showSegment();this.seek(this.run.result.segments[i].start_s);}return;}

    if(action==='select-segment'){this.stop();this.segmentIndex=Number(b.dataset.index);this.showSegment();this.seek(this.run.result.segments[this.segmentIndex].start_s);this.focusMedia();return;}
    if(action==='seek'){this.stop();if(b.dataset.camera&&this.audit?.mode==='motion')this.audit.setMode('both');if(b.dataset.camera&&this.q('#tf-camera'))this.switchCamera(b.dataset.camera);this.seek(Number(b.dataset.time));this.focusMedia();return;}
    if(action==='camera'){this.switchCamera(b.dataset.cam);return;}
    if(action==='step-frame'){this.stepFrame(Number(b.dataset.direction));return;}
    if(action==='retry-frames'){this.loadFramePlayer();return;}
    if(action==='play'){this.play();return;}
    if(action==='open-run'){this.q('#tf-setup-dialog').close();await this.loadRun(b.dataset.id);return;}
    if(action==='export'){const blob=new Blob([JSON.stringify(this.run,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`task-review-${this.run.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;}
    if(action==='add-stage'||action==='remove-stage'){this.readSpec();if(action==='add-stage')this.template.spec.stages.push({id:'manual_'+Date.now(),name:'',goal:'',success_criteria:[],repeatable:true});else this.template.spec.stages.splice(Number(b.dataset.index),1);this.renderSpec();return;}
    if(action==='edit-boundaries'){this.stop();this.message('');this.boundaries=this.run.result.segments.map(s=>({stage_id:s.stage_id,start_s:s.start_s,end_s:s.end_s}));this.renderBoundaries();return;}
    if(action==='close-boundaries'){this.q('#tf-boundary-dialog').close();this.editing=false;return;}
    if(action==='split-boundary'||action==='merge-boundary'){this.readBoundaries();const i=Number(b.dataset.index),s=this.boundaries[i];if(action==='split-boundary'){const mid=+(s.start_s+(s.end_s-s.start_s)/2).toFixed(3);this.boundaries.splice(i,1,{...s,end_s:mid},{...s,start_s:mid});}else if(this.boundaries[i+1])this.boundaries.splice(i,2,{...s,end_s:this.boundaries[i+1].end_s});this.renderBoundaries();return;}
    if(action==='close-spec'){this.q('#tf-spec-dialog').close();this.editing=false;return;}
    if(this.busy)return;this.busy=true;b.disabled=true;
    try{
      if(action==='register-record'||action==='register-path'){
        const source=action==='register-record'?{kind:'recording',id:this.q('#tf-record').value}:{kind:'video',path:this.q('#tf-path').value};
        if(!(source.id||source.path))throw Error('请先选择记录或填写视频路径。');
        const asset=await this.api('/api/taskflow/assets',{source});await this.refresh();this.q('#tf-reference').value=asset.id;this.q('#tf-target').value=asset.id;this.syncReviewRange();this.message('录像已加入，可选择范本开始审核。');this.setSetupTab(this.overview.templates.length?'review':'reference');await this.previewState(asset.id);
      }else if(action==='reference'||action==='review'){
        let asset=this.q(action==='reference'?'#tf-reference':'#tf-target').value;const template=this.q('#tf-template').value;
        if(action==='review'&&this.overview.jobs?.some(j=>j.kind==='review'&&j.asset_id===asset&&['queued','running'].includes(j.state)))throw Error('这条记录正在分析，请等待完成或先取消。');
        if(!asset)throw Error('请先添加并选择录像。');if(action==='review'&&!template)throw Error('请先解析一段范本。');
        if(this.overview.provider.model!==REVIEW_MODEL)throw Error('本机审核仅使用 HORIZON-MiniMax，请通过「MiniMax 接入」配置自己的接口。');
        const scope=action==='review'?this.selectedReviewRange():{};
        if(asset==='pending-recording'){const registered=await this.api('/api/taskflow/assets',{source:{kind:'recording',id:this.recording.id}});asset=registered.id;}
        await this.api('/api/taskflow/jobs',{kind:action,asset_id:asset,template_id:template,instruction:this.q('#tf-instruction').value,analysis_mode:this.q('#tf-mode').value,...scope});this.pinRun=false;this.q('#tf-setup-dialog').close();this.message('');await this.refresh();
      }else if(action==='cancel'){await this.api('/api/taskflow/cancel',{id:b.dataset.id});await this.refresh();}
      else if(action==='edit-template'){const id=this.q('#tf-template').value;if(!id)throw Error('请先解析一段范本。');this.message('');this.template=await this.api('/api/taskflow/template?id='+id);this.renderSpec();}
      else if(action==='save-template'){
        const spec={...this.template.spec,task_name:this.q('#tf-task-name').value,task_goal:this.q('#tf-task-goal').value,
          stages:[...this.root.querySelectorAll('[data-tf-stage]')].map((row,i)=>({...this.template.spec.stages[i],name:row.querySelector('[name=name]').value,goal:row.querySelector('[name=goal]').value,success_criteria:row.querySelector('[name=criteria]').value.split('\n').map(s=>s.trim()).filter(Boolean)}))};
        this.template=await this.api('/api/taskflow/template',{id:this.template.id,revision:this.template.revision,spec});this.editing=false;this.q('#tf-spec-dialog').close();await this.refresh();this.message('任务定义已保存。后续审核使用新版本，已有结果保留原定义。');
      }else if(action==='save-boundaries'){
        this.readBoundaries();this.run=await this.api('/api/taskflow/segments',{id:this.run.id,revision:this.run.revision,segments:this.boundaries,note:this.q('#tf-boundary-note').value});this.editing=false;this.q('#tf-boundary-dialog').close();this.segmentIndex=0;this.renderRun();await this.refresh();this.message('分段已修订。新分段的目标结果待复核，模型原始分段仍保留在导出数据中。');
      }else if(action==='save-review'){
        const index=this.segmentIndex;this.run=await this.api('/api/taskflow/review',{id:this.run.id,revision:this.run.revision,segment_id:this.run.result.segments[index].id,completion:this.q('#tf-decision').value,note:this.q('#tf-note').value});this.reviewDrafts.delete(this.run.id+':'+this.run.result.segments[index].id);this.displayedSegmentKey=null;this.renderRun();this.message('复核已保存，模型原始判断仍可查看。');await this.refresh();
      }
    }finally{this.busy=false;if(b.isConnected)b.disabled=action==='review'&&Boolean(this.overview.jobs?.some(j=>j.kind==='review'&&j.asset_id===this.q('#tf-target').value&&['queued','running'].includes(j.state)));}
  }
  async upload(file){
    if(!file)return;if(this.busy){this.message('请等当前操作完成后再上传。',true);return;}if(file.size>1024**3){this.message('单个视频请控制在1GB以内。',true);return;}
    this.busy=true;const input=this.q('#tf-upload');input.disabled=true;
    try{const asset=await new Promise((resolve,reject)=>{const x=new XMLHttpRequest();this.uploadRequest=x;x.open('POST','/api/taskflow/upload?name='+encodeURIComponent(file.name));x.setRequestHeader('Content-Type','application/octet-stream');x.upload.onprogress=e=>this.message(e.lengthComputable?`正在上传 ${Math.round(100*e.loaded/e.total)}%…`:'正在上传…');x.onerror=()=>reject(Error('上传连接中断'));x.onabort=()=>reject(Error('上传已取消'));x.onload=()=>{try{const v=JSON.parse(x.responseText);x.status<300?resolve(v):reject(Error(v.error||'上传失败'));}catch{reject(Error('上传响应无效'));}};x.send(file);});if(!this.alive)return;await this.refresh();this.q('#tf-reference').value=asset.id;this.q('#tf-target').value=asset.id;this.syncReviewRange();this.message('视频上传完成，可开始解析范本。');this.setSetupTab('reference');await this.previewState(asset.id);}catch(e){this.message(e.message,true);}finally{this.busy=false;if(input.isConnected){input.disabled=false;input.value='';}}
  }
  readSpec(){this.template.spec={...this.template.spec,task_name:this.q('#tf-task-name').value,task_goal:this.q('#tf-task-goal').value,stages:[...this.root.querySelectorAll('[data-tf-stage]')].map((row,i)=>({...this.template.spec.stages[i],name:row.querySelector('[name=name]').value,goal:row.querySelector('[name=goal]').value,success_criteria:row.querySelector('[name=criteria]').value.split('\n').map(s=>s.trim()).filter(Boolean)}))};}
  renderSpec(){
    this.editing=true;const t=this.template,e=this.e;
    this.q('#tf-spec').innerHTML=`<section class="tf-card tf-spec"><div class="tf-section-head"><h2>任务定义 · v${t.revision}</h2><span class="tf-muted">${t.spec.origin==='human_edited'?'人工已编辑':'模型建议，可修改'}</span><button data-tf="close-spec">关闭</button></div><label>任务名称<input id="tf-task-name" value="${e(t.spec.task_name)}"></label><label>总体目标<textarea id="tf-task-goal">${e(t.spec.task_goal)}</textarea></label><div class="tf-stage-defs">${t.spec.stages.map((s,i)=>`<div data-tf-stage><label>阶段名称<input name="name" value="${e(s.name)}"></label><label>阶段目标<textarea name="goal">${e(s.goal)}</textarea></label><label>完成条件 · 每行一项<textarea name="criteria">${e(s.success_criteria.join('\n'))}</textarea></label><button data-tf="remove-stage" data-index="${i}" ${t.spec.stages.length===1?'disabled':''}>移除阶段</button></div>`).join('')}</div>${t.spec.uncertainties.length?`<p class="tf-note">仍需明确：${e(t.spec.uncertainties.join('；'))}</p>`:''}<div class="tf-inline"><button data-tf="add-stage">添加阶段</button><button class="tf-primary" data-tf="save-template">保存任务定义</button></div></section>`;
    if(!this.q('#tf-spec-dialog').open)this.q('#tf-spec-dialog').showModal();
  }
  async loadRun(id){this.captureReviewDraft();const token=this.runLoadToken=(this.runLoadToken||0)+1;const run=await this.api('/api/taskflow/run?id='+id);if(!this.alive||token!==this.runLoadToken)return;if(this.recording&&!this.overview.runs.some(r=>r.id===run.id))throw Error('该分析结果不属于当前采集记录。');this.run=run;this.segmentIndex=0;this.segmentFilter='all';this.detailTab='criteria';this.q('#tf-mode').value=run.result.analysis_mode||'visual';this.q('#tf-runs').value=id;this.q('#tf-template').value=run.template_id;this.q('#tf-target').value=run.asset_id;this.syncReviewRange(run.result.analysis_range||{start_s:0,end_s:this.assets.find(a=>a.id===run.asset_id).duration_s});const template=this.overview.templates.find(t=>t.id===run.template_id);if(template)this.q('#tf-reference').value=template.asset_id;this.renderRun();this.previewState(run.asset_id).catch(err=>this.message(err.message,true));}
  renderUnreviewed(){
    const asset=this.targetAssets[0];
    // Local playback shell only: no prediction, asset registration, or persisted run.
    this.run={id:null,previewOnly:true,asset_id:asset.id,template_revision:null,template_snapshot:{},result:{segments:[],frames:[],summary:{segment_count:0,completed:0,not_completed:0,uncertain:0},analysis_range:{start_s:0,end_s:asset.duration_s},coarse_sampling:{max_sample_gap_s:0},provider:{model:'',provider_label:''}}};
    this.detailTab='manual';this.renderRun();this.updateOverview(this.overview);
  }
  renderRun(){
    this.stop();this.feedback?.destroy();this.audit?.detachPlayer();this.framePlayer?.destroy();this.framePlayer=null;const r=this.run,result=r.result,e=this.e,counts=result.summary;this.asset=this.assets.find(a=>a.id===r.asset_id);this.q('#tf-export').disabled=!r.id;
    const start=result.analysis_range?.start_s??0,end=result.analysis_range?.end_s??this.asset.duration_s;
    const record=this.catalog?.find(c=>c.id===this.asset.source.id);const cameras=Object.keys(record?.cameras||{});if(!cameras.length)cameras.push(...new Set([this.asset.source.camera,...result.frames.map(f=>f.camera)].filter(Boolean)));this.nativePlayback=this.asset.source.kind==='recording'&&!this.asset.source.snapshot&&!record?.snapshot;
    this.q('#tf-result').innerHTML=`${r.template_stale?'<p class="tf-warning">任务定义已有更新，本次结果仍基于 v'+r.template_revision+'。</p>':''}
      <div class="tf-run-context"><div>${this.recording?'':`<h2>${e(this.asset.name)}</h2>`}<span class="tf-source-tag">${this.asset.source.kind==='video'?'视频':result.state_evidence?.source==='native_feedback'?'真机 MCAP':'采集记录'}</span></div><span>${r.previewOnly?'录像范围':'检查区间'} <b>${sec(start)}–${sec(end)}</b></span></div>
      ${r.previewOnly?'<div id="tf-review-status" class="audit-no-analysis"><span>先分析任务阶段，再核对完成条件。</span><button class="tf-primary" data-tf="setup" data-tab="review">选择范本并开始</button></div>':`<details class="tf-task-context"><summary><span>任务目标</span><b>${e(r.template_snapshot.task_name)}</b><span>范本 v${r.template_revision}</span></summary><p>${e(r.template_snapshot.task_goal)}</p>${result.analysis_mode==='state'&&!result.state_evidence?.available?'<p class="tf-warning">未取得可用反馈，本次请核对画面与数据来源。</p>':''}</details>`}
      <div class="tf-audit-layout">
        <aside class="tf-stage-rail" aria-label="阶段导航" ${r.previewOnly?'hidden':''}><div class="tf-panel-heading"><h3>阶段与尝试 <span>${counts.segment_count}</span></h3><button class="tf-icon-button" data-tf="edit-boundaries" title="修订分段" aria-label="修订分段">${icon('sliders')}</button></div>
        <div class="tf-filters" aria-label="筛选阶段"><button data-tf="filter-segments" data-filter="all" aria-pressed="true">全部 ${counts.segment_count}</button><button data-tf="filter-segments" data-filter="not_completed" aria-pressed="false">未完成 ${counts.not_completed}</button><button data-tf="filter-segments" data-filter="uncertain" aria-pressed="false">待核 ${counts.uncertain}</button></div>
        <div class="tf-segments" aria-label="动作片段列表">${result.segments.map((s,i)=>`<button data-tf="select-segment" data-index="${i}" data-completion="${s.effective_completion}" class="tf-segment-row"><span class="tf-segment-number">${String(i+1).padStart(2,'0')}</span><span class="tf-segment-label"><b>${e(s.name)}</b><small>${sec(s.start_s)}–${sec(s.end_s)}</small><span class="tf-state ${s.effective_completion}">${labels[s.effective_completion]}${s.human_review?' · 人工复核':''}</span></span></button>`).join('')}<p id="tf-segment-empty" class="tf-note" hidden>当前没有这类阶段。</p></div>
        <div class="tf-rail-foot">${counts.completed} 段已完成 · ${counts.not_completed+counts.uncertain} 段需关注<small>每次尝试单独保留</small></div></aside>
        <section class="tf-visual" aria-label="录像与时间轴"><div class="tf-panel-heading"><h3>${icon('camera')} 录像回放</h3>${this.asset.source.kind!=='video'?`<div class="tf-camera-tabs" role="group" aria-label="切换相机">${cameras.map(c=>`<button data-tf="camera" data-cam="${e(c)}" aria-pressed="${c===this.asset.source.camera}">${e(cameraNames[c]||c)}</button>`).join('')}</div><select id="tf-camera" aria-label="预览相机" hidden>${cameras.map(c=>`<option value="${e(c)}" ${c===this.asset.source.camera?'selected':''}>${e(cameraNames[c]||c)}</option>`).join('')}</select>`:'<span class="tf-muted">视频回放</span>'}</div>
        <div class="tf-media">${this.asset.source.kind==='video'?`<video id="tf-video" src="/api/taskflow/video?id=${r.asset_id}" preload="metadata"></video>`:`<img id="tf-preview" ${this.nativePlayback?`data-camera="${e(this.asset.source.camera)}"`:""} alt="当前录像画面">${this.asset.source.snapshot?'<span class="tf-media-tag">缓存画面</span>':''}<span class="camera-frame" hidden></span><div id="tf-media-error" class="camera-error" hidden>此时刻的画面暂不可用，请切换相机或拖动时间轴。</div>`}</div>
        <div class="tf-player-bottom"><div class="tf-transport"><button class="tf-icon-button" data-tf="step-frame" data-direction="-1" aria-label="上一帧" title="上一帧 · ←">${icon('previous')}</button><button class="tf-play-button" data-tf="play" id="tf-play" aria-label="播放" title="播放 / 暂停 · 空格">${icon('play')}</button><button class="tf-icon-button" data-tf="step-frame" data-direction="1" aria-label="下一帧" title="下一帧 · →">${icon('next')}</button><input id="tf-scrub" type="range" min="0" max="${this.asset.duration_s}" value="0" step="any" aria-label="录像进度"><span id="tf-time">0.0s / ${sec(this.asset.duration_s)}</span><select id="tf-speed" aria-label="播放速度"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></div><div class="tf-playback-meta"><span id="tf-playback-status">${this.nativePlayback?'正在读取原始帧…':this.asset.source.snapshot?'缓存抽帧回放':'视频回放'}</span></div>
        <div class="tf-timeline-heading" ${r.previewOnly?'hidden':''}><span>${r.previewOnly?'阶段范围 · 尚未分析':'阶段时间轴'}</span></div><div class="tf-timeline" aria-label="每次尝试的时间区间" ${r.previewOnly?'hidden':''}>${result.segments.map((s,i)=>`<button data-tf="select-segment" data-index="${i}" class="${s.effective_completion}" style="position:absolute;left:${100*s.start_s/this.asset.duration_s}%;width:${100*(s.end_s-s.start_s)/this.asset.duration_s}%" title="${e(s.name)} · ${sec(s.start_s)}–${sec(s.end_s)} · ${labels[s.effective_completion]}" aria-label="第${i+1}段 ${e(s.name)} ${labels[s.effective_completion]}">${i+1}</button>`).join('')}</div>
        <p id="tf-frame-context" class="tf-frame-context" hidden></p><div class="tf-timeline-foot"><span>${result.origin==='human_segmentation'?'人工修订边界':'抽帧估计边界'} · 最大采样间隔 ${sec(result.coarse_sampling.max_sample_gap_s)}</span><span class="tf-state completed">已完成</span><span class="tf-state not_completed">未完成</span><span class="tf-state uncertain">证据不足</span></div></div>
        <section id="tf-feedback-panel" class="tf-feedback-panel" aria-label="同步机器人反馈"></section><section id="tf-evidence-panel" class="tf-evidence-panel" aria-label="当前阶段证据"></section></section>
        <aside id="tf-detail" class="tf-detail" aria-label="阶段判断与复核"></aside>
      </div>
      <footer class="tf-footnote" ${r.previewOnly?'hidden':''}><details><summary>分析信息与原始结果</summary><p>${e(result.provider.provider_label)} · ${e(result.prompt_version)}。统计保留每次失败，不代表整条任务的合格率。原始录像保留在本机。</p>${r.model_result?r.model_result.segments.map(s=>`<p>${sec(s.start_s)}–${sec(s.end_s)} · ${e(s.name)} · ${labels[s.completion]}<br>${e(s.reason)}</p>`).join(''):''}</details></footer>`;
    this.q('#tf-scrub').oninput=ev=>{this.stop();this.seek(Number(ev.target.value));};
    const video=this.q('#tf-video');if(video){video.ontimeupdate=()=>this.updateTime(video.currentTime);video.onplay=()=>{this.setPlayState(true);};video.onpause=()=>{this.setPlayState(false);};}
    const preview=this.q('#tf-preview');if(preview){preview.addEventListener('load',()=>{this.q('#tf-media-error').hidden=true;});preview.addEventListener('error',()=>{this.q('#tf-media-error').hidden=false;});}
    this.audit?.attachPlayer();this.feedback=new FeedbackPanel(this,this.q('#tf-feedback-panel'));this.feedback.load();this.showSegment();this.applySegmentFilter();this.seek(result.segments[this.segmentIndex]?.start_s||0);if(this.nativePlayback)this.loadFramePlayer();
  }
  readBoundaries(){this.boundaries=[...this.root.querySelectorAll('[data-tf-boundary]')].map(row=>({stage_id:row.querySelector('select').value||null,start_s:Number(row.querySelector('[name=start]').value),end_s:Number(row.querySelector('[name=end]').value)}));}
  renderBoundaries(){
    this.editing=true;const e=this.e;
    this.q('#tf-boundaries').innerHTML=`<section class="tf-card tf-boundary-editor"><div class="tf-section-head"><h2>修订分段</h2><button data-tf="close-boundaries">取消</button></div><p class="tf-note">修改后各段的完成判断将重置为“证据不足”，请逐段复核；原始模型结果保留。时间必须连续、按序且不重叠。</p>${this.boundaries.map((s,i)=>`<div data-tf-boundary><span>${i+1}</span><select aria-label="第${i+1}段类别"><option value="">未识别区间</option>${this.run.template_snapshot.stages.map(t=>`<option value="${e(t.id)}" ${s.stage_id===t.id?'selected':''}>${e(t.name)}</option>`).join('')}</select><input type="number" step="0.001" min="0" name="start" aria-label="第${i+1}段起点" value="${s.start_s}"><span>至</span><input type="number" step="0.001" min="0" name="end" aria-label="第${i+1}段终点" value="${s.end_s}"><button data-tf="split-boundary" data-index="${i}">拆分</button><button data-tf="merge-boundary" data-index="${i}" ${i===this.boundaries.length-1?'disabled':''}>合并下段</button></div>`).join('')}<label>修改说明<textarea id="tf-boundary-note" placeholder="根据录像说明需要调整的阶段或边界"></textarea></label><button class="tf-primary" data-tf="save-boundaries">保存修订</button></section>`;
    if(!this.q('#tf-boundary-dialog').open)this.q('#tf-boundary-dialog').showModal();
  }
  captureReviewDraft(){if(this.displayedSegmentKey&&this.q('#tf-note'))this.reviewDrafts.set(this.displayedSegmentKey,{note:this.q('#tf-note').value,completion:this.q('#tf-decision').value});}
  showSegment(){
    this.captureReviewDraft();
    const s=this.run.result.segments[this.segmentIndex],e=this.e;if(!s){
      this.displayedSegmentKey=null;
      this.q('#tf-detail').innerHTML='<div class="tf-detail-title"><h3>记录审核</h3><p class="tf-note">回看录像并记录保留意向；阶段判断需先运行 MiniMax。</p></div><div class="tf-detail-tabs" role="tablist" aria-label="记录审核信息"><button role="tab" id="tf-detail-tab-manual" aria-controls="tf-detail-manual" data-tf="detail-tab" data-tab="manual">人工复核</button></div><div class="tf-detail-body"><section role="tabpanel" id="tf-detail-manual" aria-labelledby="tf-detail-tab-manual" data-detail-panel="manual" hidden></section></div>';
      this.audit?.attachDetail();return;
    }
    this.root.querySelectorAll('[data-tf="select-segment"]').forEach(el=>{const active=Number(el.dataset.index)===this.segmentIndex;el.classList.toggle('active',active);el.setAttribute('aria-pressed',String(active));});
    const list=this.q('.tf-segments'),active=this.q('.tf-segment-row.active');if(list&&active){const r=active.getBoundingClientRect(),box=list.getBoundingClientRect();if(r.top<box.top||r.bottom>box.bottom)list.scrollTop+=r.top-box.top-list.clientHeight/2+r.height/2;if(r.left<box.left||r.right>box.right)list.scrollLeft+=r.left-box.left-list.clientWidth/2+r.width/2;}
    const frames=new Map(this.run.result.frames.map(f=>[f.id,f]));
    this.q('#tf-evidence-panel').innerHTML=`<div class="tf-panel-heading"><h3>阶段 ${String(this.segmentIndex+1).padStart(2,'0')} · 证据画面</h3></div><div class="tf-evidence">${s.evidence_frame_ids.map(id=>frames.get(id)).filter(Boolean).sort((a,b)=>a.time_s-b.time_s).map(f=>`<button data-tf="seek" data-time="${f.time_s}" data-camera="${e(f.camera||this.asset.source.camera)}" title="跳转到 ${sec(f.time_s)}"><img loading="lazy" src="${e(f.url)}" alt="${sec(f.time_s)} 的证据画面"><span>${e(cameraNames[f.camera]||'画面')} · ${sec(f.time_s)}${f.time_s>s.end_s?' · 后续观察':''}</span></button>`).join('')||'<p class="tf-note">本段暂无可核对的证据画面。</p>'}</div>`;
    this.q('#tf-detail').innerHTML=`<div class="tf-detail-title"><div class="tf-detail-head"><span>阶段 ${String(this.segmentIndex+1).padStart(2,'0')} / ${this.run.result.segments.length}</span><div class="tf-neighbors"><button class="tf-icon-button" data-tf="neighbor" data-offset="-1" aria-label="上一阶段" ${this.segmentIndex===0?'disabled':''}>${icon('left')}</button><button class="tf-icon-button" data-tf="neighbor" data-offset="1" aria-label="下一阶段" ${this.segmentIndex===this.run.result.segments.length-1?'disabled':''}>${icon('right')}</button></div></div><h3>${e(s.name)}</h3><div class="tf-detail-meta"><span class="tf-state ${s.effective_completion}">${labels[s.effective_completion]}</span><span>${sec(s.start_s)}–${sec(s.end_s)} · ${sec(s.end_s-s.start_s)}</span></div></div>
      <div class="tf-detail-tabs" role="tablist" aria-label="阶段审核信息">${[['criteria','完成条件'],['inputs','模型输入'],['manual','人工复核']].map(([key,name])=>`<button role="tab" id="tf-detail-tab-${key}" aria-controls="tf-detail-${key}" data-tf="detail-tab" data-tab="${key}">${name}</button>`).join('')}</div>
      <div class="tf-detail-body"><section role="tabpanel" id="tf-detail-criteria" aria-labelledby="tf-detail-tab-criteria" data-detail-panel="criteria"><div class="tf-verdict-note">${icon('info')} ${s.human_review?'已人工复核':'模型判断 · 待复核'}</div>${s.criteria_results.length?s.criteria_results.map((c,i)=>`<div class="tf-criterion"><div><span class="tf-condition-index">${i+1}</span><b>${e(c.criterion)}</b></div><span class="tf-state ${c.status}">${labels[c.status]}</span><details class="tf-condition-evidence"><summary>判断依据</summary><p>${e(c.reason||'尚无判断依据')}</p>${c.observability?`<small class="tf-guard-note">模型报告：${({direct:'直接可见',limited:'观测受限',unknown:'观测条件未明确'})[c.observability]||'观测条件未明确'}</small>`:''}${c.guard_note?`<small class="tf-guard-note">${e(c.guard_note)} 原模型判断：${labels[c.model_status]||'未知'}。</small>`:''}</details></div>`).join(''):'<p class="tf-note">没有足够证据判断此区间。</p>'}<details class="tf-reason-detail"><summary>${s.origin==='human_segmentation'?'分段修改说明':'阶段判断摘要'}</summary><p class="tf-reason">${e(s.reason)}</p></details></section>
      <section role="tabpanel" id="tf-detail-inputs" aria-labelledby="tf-detail-tab-inputs" data-detail-panel="inputs" hidden>${this.inputsMarkup(s)}</section><section role="tabpanel" id="tf-detail-manual" aria-labelledby="tf-detail-tab-manual" data-detail-panel="manual" hidden><p class="tf-note">${s.origin==='human_segmentation'?'分段已修订，当前片段尚无有效的模型完成判断。':'模型原始判断：'+labels[s.completion]+'。'}复核不会覆盖原始结果。</p>${s.human_review?'<div class="tf-saved-review">'+icon('check')+' 本段已保存人工复核</div>':''}<label>目标是否完成<select id="tf-decision">${Object.entries(labels).map(([k,v])=>`<option value="${k}" ${k===s.effective_completion?'selected':''}>${v}</option>`).join('')}</select></label><label>复核依据<textarea id="tf-note" placeholder="描述观察到的结果或需要补充的证据">${e(s.human_review?.note||'')}</textarea></label><button class="tf-primary" data-tf="save-review">${icon('save')} 保存复核</button></section></div>`;
    this.displayedSegmentKey=this.run.id+':'+s.id;const draft=this.reviewDrafts.get(this.displayedSegmentKey);if(draft){this.q('#tf-note').value=draft.note;this.q('#tf-decision').value=draft.completion;}
    this.audit?.attachDetail();this.setDetailTab(this.detailTab);this.renderInputRequest(this.q('#tf-input-request')?.value);this.feedback?.update(this.time||0);
  }
  inputsMarkup(segment){
    const e=this.e,manifest=this.run.model_inputs,requests=relatedRequests(manifest,segment);
    return `${segment.origin==='human_segmentation'?'<p class="tf-note">当前边界经人工修改；以下保留原分析请求，不是针对新边界重新推理。</p>':''}${requests.length?`<label class="tf-input-select"><span>分析请求</span><select id="tf-input-request" aria-label="与当前阶段相关的请求">${requests.map((r,i)=>`<option value="${e(r.id)}" ${i===requests.length-1?'selected':''}>${r.kind==='verify'?'目标核查':'阶段识别'} · ${r.range?sec(r.range.start_s)+'–'+sec(r.range.end_s):'范围未存档'}${r.cached?' · 缓存复用':''}</option>`).join('')}</select></label><div id="tf-input-content"></div>`:`<p class="tf-note">${e(manifest?.reason||'没有与此阶段对应的请求存档。')}</p>`}${manifest?.unreadable?`<p class="tf-warning">${manifest.unreadable} 份存档无法读取，当前列表不完整。</p>`:''}${segment.state_evidence?`<details class="tf-local-summary"><summary>本阶段反馈摘要 · 本机整理</summary><p class="tf-note">按最终阶段范围汇总，可能与模型收到的观察窗口不同。</p>${this.stateMarkup(segment.state_evidence,true)}</details>`:''}`;
  }
  renderInputRequest(id){
    const request=this.run.model_inputs?.requests.find(r=>r.id===id),host=this.q('#tf-input-content');if(!host||!request)return;
    const e=this.e,targets=request.frames.filter(f=>f.role!=='reference'),references=request.frames.filter(f=>f.role==='reference');
    host.innerHTML=`${request.model&&request.model!==this.run.result.provider?.model?`<p class="tf-note">请求模型：${e(request.model)}</p>`:''}<details class="tf-input-frame-list"><summary>${targets.length} 张目标画面${references.length?' ＋ '+references.length+' 张范本画面':''} · 点击定位</summary><div class="tf-input-frames">${targets.map(f=>`<button data-tf="seek" data-time="${f.time_s}" data-camera="${e(f.camera||this.asset.source.camera)}" title="输入画面 · ${e(cameraNames[f.camera]||'相机')}">${sec(f.time_s)} · ${e(cameraNames[f.camera]||'画面')}</button>`).join('')}</div></details>${request.state?`<div class="tf-input-section-heading"><h4>反馈摘要</h4><span>${sec(request.state.start_s)}–${sec(request.state.end_s)}</span></div>${this.stateMarkup(request.state,true,true)}`:'<p class="tf-note">本次请求只有画面与任务文字。本机仍可查看已关联的关节反馈，但它未作为此请求的反馈输入。</p>'}<details class="tf-input-json"><summary>查看存档输入 JSON</summary><pre>${e(JSON.stringify({frames:request.frames,state:request.state},null,2))}</pre></details>`;
  }
  async previewState(id){
    const token=this.statePreviewToken=(this.statePreviewToken||0)+1;
    if(!id||id==='pending-recording'){this.q('#tf-state-preview').innerHTML='';return;}
    const data=await this.api('/api/taskflow/state?id='+id);if(!this.alive||token!==this.statePreviewToken)return;
    this.q('#tf-state-preview').innerHTML=`<details class="tf-card"><summary>整段机器人反馈预览 · ${data.available?`${data.candidate_count} 个变化候选`:'反馈不可用'} · 本机读取</summary>${this.q('#tf-mode').value==='visual'?'<p class="tf-note">当前选择纯视觉对照，以下反馈不会作为该模式的模型输入。</p>':''}${this.stateMarkup(data,false)}</details>`;
  }
  stateMarkup(data,interactive,compact=false){
    const e=this.e;if(!data.available)return `<p class="tf-note">${e(data.reason||'未取得状态反馈')}</p>`;
    const names={left_hand:'左手反馈',right_hand:'右手反馈',left_wrist:'左腕相对骨盆',right_wrist:'右腕相对骨盆',body_rotation:'身体角速度',leg_joints:'下肢关节变化'};
    return `<div class="tf-state-facts${compact?' tf-state-compact':''}"><h4>机器人反馈 · ${data.source==='native_feedback'?'实测反馈摘要':'重采样状态快照'}</h4>${(data.facts||[]).map(f=>`<div><span>${e(compact&&f.kind==='hand_closure_feedback'?(f.side==='left'?'左手 · 0–1':'右手 · 0–1'):(names[f.track]||f.track))}</span><b><span class="tf-fact-value">${f.observed_path_m!==undefined?f.observed_path_m.toFixed(3):f.min_value!==undefined?f.min_value.toFixed(3)+'–'+f.max_value.toFixed(3):'缺少有效读数'}</span><span class="tf-fact-unit">${f.observed_path_m!==undefined?'m 路径':f.min_value!==undefined?e(f.kind==='hand_closure_feedback'?(compact?'':'闭合量（0–1）'):f.unit):''}</span></b>${!compact||f.coverage<1?`<small>有效覆盖 ${(100*f.coverage).toFixed(0)}%</small>`:''}${!compact&&f.start_value!==undefined?`<span class="tf-fact-transition">起 ${f.start_value.toFixed(3)} → 止 ${f.end_value.toFixed(3)}</span>`:''}</div>`).join('')}<p class="tf-note">${compact?'已发送的统计摘要，非逐关节时序':'腕部数值相对机身；手指收拢不代表抓住物体；未使用整机世界位移或目标物位置。'}</p>${compact?`<details class="tf-feedback-events"><summary>反馈变化 <span>${data.event_count??data.events?.length??0} 条 · 点击定位</span></summary>`:''}<div class="tf-state-events">${(data.events||[]).slice(0,12).map(ev=>interactive?`<button data-tf="seek" data-time="${Math.max(ev.start_s,data.start_s)}">${sec(Math.max(ev.start_s,data.start_s))}–${sec(Math.min(ev.end_s,data.end_s))} · ${e(ev.label)}</button>`:`<p>${sec(ev.start_s)}–${sec(ev.end_s)} · ${e(ev.label)}</p>`).join('')}</div>${data.event_count>12?`<p class="tf-note">共 ${data.event_count} 个变化候选，此处显示最多 12 个。</p>`:''}${data.warnings?.length?`<p class="tf-note">${e(data.warnings.join('；'))}</p>`:''}${compact?'</details><details class="tf-input-limits"><summary>输入说明与边界</summary><p class="tf-note">观察窗口可包含阶段前后上下文。模型收到统计与事件摘要，未收到完整关节时序。腕部数值相对骨盆；手指收拢不代表抓住物体，未使用整机世界位移或目标物位置。</p></details>':''}</div>`;
  }
  focusMedia(){const media=this.q('.tf-media');if(!media)return;const r=media.getBoundingClientRect();if(r.top<60||r.bottom>innerHeight)media.scrollIntoView({behavior:'smooth',block:'center'});}
  updateTime(t){
    if(!this.alive||!this.q('#tf-scrub'))return;this.time=t;this.audit?.updateTime(t);this.feedback?.update(t);this.q('#tf-scrub').value=t;this.q('#tf-time').textContent=sec(t)+' / '+sec(this.asset.duration_s);
    const current=this.run.result.segments.findIndex((s,i)=>t>=s.start_s&&(t<s.end_s||(i===this.run.result.segments.length-1&&t<=s.end_s))),context=this.q('#tf-frame-context');
    if(context){context.hidden=this.run.previewOnly||current===this.segmentIndex;context.textContent=current<0?'当前画面位于本次检查区间之外。':`画面位于第 ${current+1} 段，右侧正在审核第 ${this.segmentIndex+1} 段。`;}
  }
  setPlayState(playing){const b=this.q('#tf-play');if(b){b.innerHTML=icon(playing?'pause':'play');b.setAttribute('aria-label',playing?'暂停':'播放');b.setAttribute('aria-pressed',String(playing));}}
  playbackStatus(text){const el=this.q('#tf-playback-status');if(el)el.textContent=text;}
  async loadFramePlayer(){
    this.framePlayer?.destroy();const player=new FramePlayer(this.asset.source.id,{root:this.root,indexUrl:this.run.previewOnly?'/api/frame-index?ep='+this.asset.source.id:'/api/taskflow/frame-index?id='+this.asset.id,status:(text,error)=>{if(this.framePlayer!==player)return;this.playbackStatus(text);if(error){this.stop();this.playbackStatus(text);const box=this.q('#tf-media-error');box.hidden=false;box.textContent=text;const retry=document.createElement('button');retry.dataset.tf='retry-frames';retry.textContent='重新加载';box.append(retry);}},painted:()=>{if(this.framePlayer!==player)return;const img=this.q('#tf-preview');img.parentElement.style.setProperty('--tf-head-ratio',img.naturalWidth/img.naturalHeight/2);this.paintedFrames=(this.paintedFrames||0)+1;}});
    this.framePlayer=player;player.time=this.time||0;this.configureNativeCamera();
    try{await player.load();if(this.framePlayer===player&&this.alive){player.update(this.time||0);this.playbackStatus('原始帧回放 · 支持逐帧核对');}}
    catch(err){if(this.framePlayer===player&&this.alive){this.playbackStatus(err.message);const box=this.q('#tf-media-error');box.hidden=false;box.textContent=err.message;}}
  }
  configureNativeCamera(){
    const img=this.q('#tf-preview');if(!img||!this.nativePlayback)return;
    const camera=this.q('#tf-camera').value;img.dataset.camera=camera;
    const record=this.catalog?.find(c=>c.id===this.asset.source.id);
    img.parentElement.classList.toggle('tf-stereo-left',camera==='head'&&(record?.head_camera_mode==='stereo_sbs'||this.asset.source.crop==='left'));
  }
  switchCamera(camera){
    const select=this.q('#tf-camera');if(!select||![...select.options].some(o=>o.value===camera))return;
    select.value=camera;this.root.querySelectorAll('[data-tf="camera"]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.cam===camera)));
    this.configureNativeCamera();if(this.framePlayer){this.framePlayer.last.clear();this.framePlayer.displayBusy.clear();const box=this.q('#tf-media-error');box.hidden=false;box.textContent='正在载入'+(cameraNames[camera]||camera)+'画面…';}this.seek(this.time||0);
  }
  stepFrame(direction){
    this.stop();const camera=this.q('#tf-camera')?.value,times=this.framePlayer?.index?.cameras[camera]?.times_s;
    if(times?.length){const i=adjacentFrame(times,this.time||0,direction,Number(this.q('#tf-preview')?.dataset.frameIndex));this.updateTime(times[i]);this.framePlayer.update(times[i],false,{cam:camera,index:i});}
    else this.seek(Math.max(0,Math.min(this.asset.duration_s,(this.time||0)+direction*(this.asset.source.snapshot ? .5 : 1/30))));
  }
  seek(t){
    t=Math.max(0,Math.min(this.asset.duration_s,t));this.updateTime(t);const video=this.q('#tf-video');if(video){if(Math.abs(video.currentTime-t)>.01)video.currentTime=t;return;}
    if(this.nativePlayback){this.framePlayer?.update(t,this.playing);return;}
    const previewTime=Math.min(t,Math.floor(this.asset.duration_s*1000)/1000);
    const img=this.q('#tf-preview');if(img)img.src=this.run.previewOnly?`/api/frame?ep=${this.asset.source.id}&cam=${encodeURIComponent(this.q('#tf-camera')?.value||this.asset.source.camera)}&t=${previewTime.toFixed(3)}`:`/api/taskflow/preview?id=${this.run.asset_id}&t=${previewTime.toFixed(3)}&cam=${encodeURIComponent(this.q('#tf-camera')?.value||this.asset.source.camera)}`;
  }
  play(){
    const video=this.q('#tf-video');if(video){video.playbackRate=Number(this.q('#tf-speed').value);if(video.paused)video.play().catch(e=>this.message(e.message,true));else video.pause();return;}
    if(this.playing){this.stop();return;}
    if(this.nativePlayback&&!this.framePlayer?.index){this.playbackStatus('帧索引加载中，请稍候');return;}
    this.playing=true;this.setPlayState(true);const epoch=++this.playerEpoch;let last=performance.now(),report=last,preview=0;this.paintedFrames=0;
    if(this.time>=this.asset.duration_s)this.seek(this.run.result.analysis_range?.start_s||0);
    const tick=now=>{
      if(!this.playing||epoch!==this.playerEpoch||!this.alive)return;
      const t=advancePlayback(this.time||0,now,last,Number(this.q('#tf-speed').value),this.asset.duration_s);last=now;
      if(this.nativePlayback)this.seek(t);else{this.updateTime(t);if(now-preview>300){this.seek(t);preview=now;}}
      if(now-report>=1000&&this.nativePlayback){this.playbackStatus(`播放中 · ${Math.round(this.paintedFrames*1000/(now-report))} 帧/秒`);this.paintedFrames=0;report=now;}
      if(t>=this.asset.duration_s){this.stop();return;}
      this.playTimer=requestAnimationFrame(tick);
    };this.playTimer=requestAnimationFrame(tick);
  }
  stop(){const wasPlaying=this.playing;this.playing=false;if(wasPlaying)this.playbackStatus(this.nativePlayback?'已暂停 · 原始帧回放':'已暂停');this.playerEpoch++;cancelAnimationFrame(this.playTimer);this.setPlayState(false);this.q('#tf-video')?.pause();}
  destroy(){this.alive=false;this.feedback?.destroy();this.audit?.destroy();this.stop();this.framePlayer?.destroy();clearInterval(this.timer);this.uploadRequest?.abort();this.root.removeEventListener('click',this.click);this.root.removeEventListener('change',this.change);this.root.removeEventListener('input',this.input);this.root.removeEventListener('keydown',this.keydown);this.root.classList.remove('tf-root','tf-config-only');}
}
