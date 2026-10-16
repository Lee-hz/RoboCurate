import {reviewLabels} from './workflow.mjs';
// Motion evidence and human selection share the VLM review clock.
import {EpisodeData} from './viewer/data.js';

const seconds=t=>Number(t).toFixed(2)+'s';
const copy=v=>JSON.parse(JSON.stringify(v));

export class AuditTools {
  constructor(owner,record) {
    this.owner=owner;this.record=record;this.alive=true;this.mode='camera';
    this.draft=copy(record.review||{revision:0,grade:'',note:'',instruction:'',segments:[],event_decisions:{}});
    this.draft.segments||=[];this.draft.event_decisions||={};
    try {const saved=JSON.parse(localStorage.getItem('rds-draft-'+record.id));if(saved?.revision===this.draft.revision){this.draft=saved;this.dirty=true;}}catch{}
    this.click=e=>{const b=e.target.closest('[data-audit]');if(b)this.action(b).catch(err=>owner.message(err.message,true));};
    this.change=e=>this.changed(e.target);
    owner.root.addEventListener('click',this.click);owner.root.addEventListener('change',this.change);
    this.input=e=>{if(['audit-note','audit-instruction'].includes(e.target.id))this.changed(e.target);};owner.root.addEventListener('input',this.input);
  }
  q(s){return this.owner.q(s);}
  persist(){this.dirty=true;try{localStorage.setItem('rds-draft-'+this.record.id,JSON.stringify(this.draft));}catch{}const b=this.q('#audit-save');if(b)b.textContent='保存保留结论';const s=this.q('#audit-save-status');if(s)s.textContent='有未保存修改';}
  attachPlayer(){
    const media=this.q('.tf-media');if(!media)return;
    const stage=document.createElement('div');stage.className='audit-stage';stage.dataset.view=this.mode;media.before(stage);stage.append(media);
    stage.insertAdjacentHTML('beforeend',`<section class="audit-motion" hidden aria-label="机器人 3D 回放"><div class="audit-motion-toolbar"><select id="audit-part" aria-label="轨迹部位"><option value="wrist">双腕轨迹</option><option value="foot">双脚轨迹</option><option value="all">全身轨迹</option></select><select id="audit-view" aria-label="3D 视角"><option value="iso">斜视</option><option value="front">正视</option><option value="side">侧视</option><option value="top">俯视</option></select><button data-audit="fit">适配</button><details><summary>显示</summary><div><label><input id="audit-target" type="checkbox"> 指令对照</label><label><input id="audit-ghost" type="checkbox"> 实测残影</label><label>轨迹窗口<select id="audit-window"><option value="2">过去 2 秒</option><option value="5">过去 5 秒</option><option value="10">过去 10 秒</option></select></label></div></details></div><div id="audit-robot-host"></div><div class="audit-motion-note"><span id="audit-robot-status">按需加载 G1 模型</span><span id="audit-motion-time">0.00s</span></div><p class="audit-coordinate-note">实测姿态 · 轨迹相对骨盆，非世界位移 · 拖动旋转 / 滚轮缩放</p></section>`);
    const heading=this.q('.tf-visual>.tf-panel-heading');
    heading.insertAdjacentHTML('beforebegin',`<div class="audit-viewbar"><b>同步回放</b><div role="group" aria-label="回放视图">${[['camera','相机'],['motion','3D'],['both','联看']].map(([key,label])=>`<button data-audit="view" data-view="${key}" aria-pressed="${key===this.mode}">${label}</button>`).join('')}</div></div>`);
    const bar=this.q('.audit-viewbar');for(const el of [...heading.children])if(!el.matches('h3'))bar.append(el);heading.remove();
    this.setMode(this.mode);
  }
  attachDetail(){
    const manual=this.q('#tf-detail-manual');if(!manual)return;
    manual.insertAdjacentHTML('beforeend','<section id="audit-retention" class="audit-retention"></section>');
    this.renderRetention();this.owner.setDetailTab(this.owner.detailTab);
  }
  renderRetention(){
    const host=this.q('#audit-retention');if(!host)return;const esc=this.owner.e,d=this.draft;
    if(this.record.snapshot){host.innerHTML='<p class="tf-note">历史快照只读。保存保留结论需要原始记录。</p>';return;}
    host.innerHTML=`<h4>数据保留与导出</h4><p class="tf-note">结合阶段目标、失败尝试与证据决定保留范围。失败片段也可保留用于后续训练。</p><label>保留结论<select id="audit-grade">${[['','待审核'],...Object.entries(reviewLabels)].map(([v,l])=>`<option value="${v}" ${d.grade===v?'selected':''}>${l}</option>`).join('')}</select></label><label>任务指令<textarea id="audit-instruction" maxlength="2000" placeholder="描述这条数据要训练的具体任务">${esc(d.instruction||'')}</textarea></label><label>数据审核说明<textarea id="audit-note" maxlength="10000">${esc(d.note||'')}</textarea></label><details><summary>保留片段 · ${d.segments.length?d.segments.length+' 个':'整段'}</summary><p class="tf-note">不设置片段时保留整段；片段不能重叠。</p><div class="audit-clip-inputs"><label>起点<input id="audit-clip-start" type="number" min="0" step="any" value="${this.owner.run?.result.segments[this.owner.segmentIndex]?.start_s??0}"></label><label>终点<input id="audit-clip-end" type="number" min="0" step="any" value="${this.owner.run?.result.segments[this.owner.segmentIndex]?.end_s??this.record.duration_s}"></label></div><button data-audit="clip-add">加入保留片段</button>${d.segments.map((s,i)=>`<p>${seconds(s.start)}–${seconds(s.end)} · ${esc(s.label)} <button data-audit="clip-remove" data-index="${i}" aria-label="移除片段 ${i+1}">移除</button></p>`).join('')}</details><button id="audit-save" class="tf-primary" data-audit="save">保存保留结论</button><span id="audit-save-status" role="status">${this.dirty?'有未保存修改':d.updated_at?'已保存':'尚未保存人工结论'}</span>`;
  }
  changed(el){
    const field={'audit-grade':'grade','audit-note':'note','audit-instruction':'instruction'}[el.id];if(field){this.draft[field]=el.value;this.persist();}
    if(el.id==='audit-view')this.robot?.setView(el.value);
    if(['audit-part','audit-target','audit-ghost','audit-window'].includes(el.id))this.robotOptions();
  }
  async action(b){
    const action=b.dataset.audit;
    if(action==='view')return this.setMode(b.dataset.view);
    if(action==='fit')return this.robot?.fitView();
    if(action==='compat'||action==='robot-retry'){this.robot?.destroy();this.robot=null;return this.loadRobot(action==='compat');}
    if(action==='prepare'){
      b.disabled=true;await this.owner.api('/api/analyze',{ids:[this.record.id]});this.owner.message('正在准备本机回放数据…');
      clearInterval(this.prepareTimer);this.prepareTimer=setInterval(async()=>{try{const c=await this.owner.api('/api/catalog');if(!this.alive)return;const r=c.episodes.find(r=>r.id===this.record.id);if(r?.cache==='ready'){clearInterval(this.prepareTimer);Object.assign(this.record,r);this.owner.loadFramePlayer();if(this.mode!=='camera')this.loadRobot();}else if(r?.cache==='error'){clearInterval(this.prepareTimer);this.owner.message(r.cache_message||'回放数据准备失败',true);}}catch(err){clearInterval(this.prepareTimer);if(this.alive)this.owner.message(err.message,true);}},2000);return;
    }
    if(action==='clip-remove'){this.draft.segments.splice(Number(b.dataset.index),1);this.persist();this.renderRetention();return;}
    if(action==='clip-add'){
      const start=Number(this.q('#audit-clip-start').value),end=Number(this.q('#audit-clip-end').value);
      if(!Number.isFinite(start+end)||start<0||end>this.record.duration_s||end-start<.1)throw Error('保留片段必须在录像内，且至少 0.1 秒。');
      if(this.draft.segments.some(s=>start<s.end&&end>s.start))throw Error('保留片段不能重叠。');
      this.draft.segments.push({start,end,label:this.owner.run?.result.segments[this.owner.segmentIndex]?.name||'保留片段',grade:['A','B','C','D'].includes(this.draft.grade)?this.draft.grade:'B'});this.draft.segments.sort((a,b)=>a.start-b.start);this.persist();this.renderRetention();return;
    }
    if(action==='save'){
      if(this.saving)return;this.saving=true;b.disabled=true;const snapshot=copy(this.draft);const {event_decisions,event_evidence,...review}=snapshot;
      try{const result=await this.owner.api('/api/reviews',{changes:[{id:this.record.id,review}]});this.record.review=result.reviews[this.record.id];if(JSON.stringify(this.draft)===JSON.stringify(snapshot)){this.draft=copy(this.record.review);this.dirty=false;localStorage.removeItem('rds-draft-'+this.record.id);}else{this.draft.revision=this.record.review.revision;this.persist();}if(this.alive){this.renderRetention();this.owner.message('数据保留结论已保存。');}}
      finally{this.saving=false;if(b.isConnected)b.disabled=false;}return;
    }
  }
  setMode(mode){
    this.mode=['camera','motion','both'].includes(mode)?mode:'camera';const stage=this.q('.audit-stage');if(!stage)return;
    stage.dataset.view=this.mode;this.q('.tf-media').hidden=this.mode==='motion';this.q('.audit-motion').hidden=this.mode==='camera';
    this.owner.root.querySelectorAll('[data-audit="view"]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===this.mode)));
    if(this.robot){this.robot.visible=this.mode!=='camera';requestAnimationFrame(()=>{if(this.alive){this.robot?.resize();this.updateTime(this.owner.time||0);}});}
    else if(this.mode!=='camera')this.loadRobot();
  }
  async loadRobot(compat=false){
    if(this.robotLoading||!this.alive)return;const host=this.q('#audit-robot-host');if(!host)return;
    if(this.record.cache!=='ready'){host.innerHTML='<p class="tf-note">需要准备关节回放数据。</p><button data-audit="prepare">准备 3D 回放</button>';return;}
    this.robotLoading=true;host.dataset.ready='false';host.innerHTML='<div class="tf-empty-small">正在加载 G1 模型与实测反馈…</div>';
    try{
      const [{RobotView},data]=await Promise.all([import('./viewer/robot3d.js'),this.data?Promise.resolve(this.data):EpisodeData.load(this.record.id)]);
      if(!this.alive||host!==this.q('#audit-robot-host'))return;this.data=data;
      if(!data.has('state.q'))throw Error('此记录缺少实际关节状态，无法回放实测姿态。');
      const description=await RobotView.describe();if(!description.ok)throw Error(description.reason);if(!this.alive||host!==this.q('#audit-robot-host'))return;
      host.innerHTML='';let robot;
      if(compat){const {SolidCanvasView}=await import('./solid-canvas.js');if(!this.alive)return;robot=new SolidCanvasView(host,data,description.desc);}else robot=new RobotView(host,data,{},description.desc);
      this.robot=robot;await robot.mount();if(!this.alive||host!==this.q('#audit-robot-host')){robot.destroy();return;}
      this.robotOptions();robot.visible=this.mode!=='camera';robot.onSeek=t=>{this.owner.stop();this.owner.seek(t);};robot.resize();this.updateTime(this.owner.time||0);host.dataset.ready='true';
      this.q('#audit-robot-status').textContent=compat?'G1 · 简化兼容渲染':'G1 · 完整模型';
      if(!this.record.snapshot){try{const tracks=await this.owner.api('/api/trajectories?ep='+this.record.id);if(this.alive&&this.robot===robot){robot.setTrajectories(tracks);this.updateTime(this.owner.time||0);this.q('#audit-robot-status').textContent+=' · '+(tracks.unavailable.length?'部分轨迹缺失':'原始采样轨迹');}}catch(err){if(this.alive)this.q('#audit-robot-status').textContent='姿态已加载 · 轨迹不可用：'+err.message;}}
    }catch(err){if(this.alive&&host===this.q('#audit-robot-host')){this.robot?.destroy();this.robot=null;host.innerHTML=`<div class="tf-empty-small"><p>3D 暂不可用：${this.owner.e(err.message)}</p><button data-audit="robot-retry">重试完整模型</button> <button data-audit="compat">兼容预览</button></div>`;}}
    finally{this.robotLoading=false;}
  }
  robotOptions(){if(!this.robot)return;Object.assign(this.robot.opts,{source:'state.q',applyImu:false,trailPart:this.q('#audit-part').value,trailWindow:Number(this.q('#audit-window').value),showTargets:this.q('#audit-target').checked,showGhost:this.q('#audit-target').checked,showPoseTrail:this.q('#audit-ghost').checked});this.updateTime(this.owner.time||0);}
  updateTime(t){
    const label=this.q('#audit-motion-time');if(label)label.textContent=seconds(t);
    const host=this.q('#audit-robot-host');if(host)host.dataset.time=String(t);
    if(this.robot?.solid&&this.robot.visible){this.robot.pose(Math.min(this.data.samples-1,Math.round(t*this.data.meta.timeline.rate_hz)));this.robot.setTime(t);}
  }
  detachPlayer(){this.robot?.destroy();this.robot=null;this.robotLoading=false;}
  destroy(){this.alive=false;clearInterval(this.prepareTimer);this.detachPlayer();this.owner.root.removeEventListener('click',this.click);this.owner.root.removeEventListener('change',this.change);this.owner.root.removeEventListener('input',this.input);}
}
