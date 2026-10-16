import * as THREE from 'three';
import {advancePlayback} from './playback-clock.mjs';
import {RobotView} from './viewer/robot3d.js';
import {EpisodeData} from './viewer/data.js';

const labels={A:'参考范围内',B:'单项偏离',C:'多项需复核',D:'任务未完成',E:'记录不完整',R:'结果待复核'};
const colors=['#839acb','#bc9a63','#64b6a4','#a993ce','#9197a2','#5b6373'];
const n=(v,d=2)=>Number.isFinite(v)?v.toFixed(d):'—';

class WorldView extends RobotView{
  _buildScene(){super._buildScene();this.canvas.style.pointerEvents='none';}
  _groundOffset(){this.standHeight=0;}
  _applyRoot(robot,sample){
    robot.root.position.set(...[0,1,2].map(i=>this.data.value('base.pos',i,sample)));
    const q=[0,1,2,3].map(i=>this.data.value('imu.quat',i,sample));
    robot.root.quaternion.set(q[1],q[2],q[3],q[0]).normalize();
    if(this.floorShadow)this.floorShadow.position.set(robot.root.position.x,robot.root.position.y,.002);
  }
  install(payload){
    const geom=payload.geometry;
    const box=(size,pos,color,opacity=1)=>{
      const object=new THREE.Mesh(new THREE.BoxGeometry(...size),new THREE.MeshStandardMaterial({color,roughness:.85,transparent:opacity<1,opacity}));
      object.position.set(...pos);this.scene.add(object);return object;
    };
    for(const [key,color] of [['source_table_origin_m',0x777583],['destination_table_origin_m',0x686f7e]]){
      const p=geom[key],height=p[2]*2;
      box([.62,.56,.035],[p[0],p[1],height],color,.4);
      for(const dx of [-.25,.25])for(const dy of [-.22,.22])box([.025,.025,height],[p[0]+dx,p[1]+dy,height/2],color,.4);
    }
    const bp=geom.basket_origin_m;
    this.basket=new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(.28,.23,.12)),new THREE.LineBasicMaterial({color:0xcba866}));
    this.basket.position.set(...bp);this.scene.add(this.basket);
    this.target=new THREE.Mesh(new THREE.CapsuleGeometry(.012,.13,5,10),new THREE.MeshStandardMaterial({color:0xea675f,roughness:.7}));
    this.target.rotation.z=Math.PI/2;this.scene.add(this.target);
    for(const [key,color] of [['base_m',0x79a8e7],['target_m',0xea887a]]){
      const points=payload.trace[key].map(p=>new THREE.Vector3(p[0],p[1],key==='base_m'?.015:p[2]));
      const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color,transparent:true,opacity:.75}));
      this.scene.add(line);
    }
    for(const ev of payload.events.filter(e=>e.needs_review)){
      const sphere=new THREE.Mesh(new THREE.SphereGeometry(.035,12,8),new THREE.MeshBasicMaterial({color:0xe5b357}));
      sphere.position.set(ev.position_m[0],ev.position_m[1],.04);this.scene.add(sphere);
    }
    this.camera.position.set(2.6,-3.2,2.7);this.controls.target.set(-.1,.9,.55);this.controls.update();
    this.canvas.style.pointerEvents='auto';this.pose(0);this.resize();this.dirty=true;
  }
  pose(sample){
    super.pose(sample);
    if(this.target){const ns=this.data.meta.channels['objects.pos'].names;this.target.position.set(...'xyz'.split('').map(a=>this.data.value('objects.pos',ns.indexOf('target.pos_'+a),sample)));}
  }
}

export class SimDemo{
  constructor(host,api,escape){Object.assign(this,{host,api,e:escape});this.closed=false;this.generation=0;this.time=0;this.playing=false;this.speed=1;}
  destroy(){this.closed=true;this.generation++;this.playing=false;cancelAnimationFrame(this.raf);this.view?.destroy();}
  async mount(){
    this.host.innerHTML='<div class="loading-page">正在准备仿真参考演示…</div>';
    this.index=await this.api('/api/sim-demo');if(this.closed)return;
    await this.select(this.index.default_id);
  }
  async select(id){
    const generation=++this.generation;this.playing=false;cancelAnimationFrame(this.raf);this.view?.destroy();this.view=null;this.data=null;
    this.host.innerHTML='<div class="loading-page">正在读取世界坐标和动作记录…</div>';
    const payload=await this.api('/api/sim-demo?ep='+id);if(this.closed||generation!==this.generation)return;
    this.p=payload;this.time=0;this.frameIndex=-1;this.render();this.update();this.tick(0);
    try{
      const [data,desc]=await Promise.all([EpisodeData.load(id),RobotView.describe()]);
      if(this.closed||generation!==this.generation)return;
      if(!desc.ok)throw Error(desc.reason);
      const host=this.host.querySelector('#sim-world');host.innerHTML='';
      const view=new WorldView(host,data,{},desc.desc);this.view=view;
      await view.mount(()=>{});if(this.closed||generation!==this.generation){view.destroy();return;}
      view.install(payload);this.data=data;this.update();
      this.host.querySelector('#sim-world-status').textContent='G1 世界坐标回放';
    }catch(error){
      if(this.closed||generation!==this.generation)return;
      try{this.view?.destroy();}catch{}this.view=null;
      this.host.querySelector('#sim-world').hidden=true;this.host.querySelector('#sim-map').hidden=false;
      this.host.querySelector('#sim-world-status').textContent='俯视轨迹图 · 三维不可用';
    }
  }
  mapHTML(){
    const p=this.p,pts=[...p.trace.base_m,...p.trace.target_m,p.geometry.source_table_origin_m,p.geometry.destination_table_origin_m];
    const minx=Math.min(...pts.map(p=>p[0]))-.5,maxx=Math.max(...pts.map(p=>p[0]))+.5;
    const miny=Math.min(...pts.map(p=>p[1]))-.5,maxy=Math.max(...pts.map(p=>p[1]))+.5;
    const scale=Math.min(660/(maxx-minx),430/(maxy-miny));
    this.mapPoint=p=>[350+(p[0]-(minx+maxx)/2)*scale,245-(p[1]-(miny+maxy)/2)*scale];
    const path=key=>p.trace[key].map((x,i)=>`${i?'L':'M'}${this.mapPoint(x).map(v=>v.toFixed(1)).join(',')}`).join(' ');
    return `<svg viewBox="0 0 700 490" role="img" aria-label="仿真世界坐标俯视轨迹"><defs><pattern id="sim-grid" width="35" height="35" patternUnits="userSpaceOnUse"><path d="M35 0H0V35" fill="none" stroke="#363845" stroke-width=".5"/></pattern></defs><rect width="700" height="490" fill="url(#sim-grid)"/>
      ${[['source_table_origin_m','取物桌'],['destination_table_origin_m','放置桌'],['basket_origin_m','篮筐']].map(([key,label])=>{const [x,y]=this.mapPoint(p.geometry[key]);return `<rect x="${x-28}" y="${y-20}" width="56" height="40" rx="4" fill="#b1a0cc18" stroke="#9693a1" stroke-dasharray="4 3"/><text x="${x}" y="${y-28}" text-anchor="middle" fill="#c8c4d0" font-size="13">${label}</text>`}).join('')}
      <path d="${path('base_m')}" stroke="#79a8e7" stroke-width="2.5" fill="none"/><path d="${path('target_m')}" stroke="#ea887a" stroke-width="2" fill="none"/>
      ${p.events.map((ev,i)=>{const [x,y]=this.mapPoint(ev.position_m);return `<circle data-sim-event="${i}" cx="${x}" cy="${y}" r="${ev.needs_review?7:4}" fill="${ev.needs_review?'#e5b357':'#8d91a6'}" opacity=".85"><title>${this.e(ev.label)} ${n(ev.start_s)}–${n(ev.end_s)} s</title></circle>`}).join('')}
      <circle id="sim-base-dot" r="10" fill="#79a8e7" stroke="#d5e5fb" stroke-width="2"/><circle id="sim-target-dot" r="6" fill="#f48b80"/><text x="15" y="474" fill="#9693a1" font-size="12">世界坐标 · 外形示意</text></svg>`;
  }
  chartHTML(){
    const tr=this.p.trace,max=Math.max(.7,...tr.speed_m_s),duration=this.p.record.duration_s;
    const path=tr.times_s.map((t,i)=>`${i?'L':'M'}${t/duration*900},${100-tr.speed_m_s[i]/max*80}`).join(' ');
    return `<svg viewBox="0 0 900 130" preserveAspectRatio="none" aria-label="基座水平速度与低速区间">${this.p.events.map(ev=>`<rect x="${ev.start_s/duration*900}" y="5" width="${ev.duration_s/duration*900}" height="100" fill="${ev.needs_review?'#daa84930':'#8c94a018'}"/>`).join('')}<path d="${path}" fill="none" stroke="#82a8d9" stroke-width="2"/><line id="sim-cursor" x1="0" x2="0" y1="0" y2="108" stroke="#e4d9f8"/><text x="3" y="123" fill="#9693a1" font-size="11">0 s</text><text x="850" y="123" fill="#9693a1" font-size="11">${n(duration,1)} s</text></svg>`;
  }
  qualityHTML(){
    const p=this.p,e=this.e,events=p.quality_events||[],m=p.record.metrics;
    return `<section class="sim-card sim-attempts"><div class="sim-card-title"><b>逐段质量与重试</b><span>${p.segments.filter(s=>s.stage<5).length} 个识别段 · 段数不固定</span></div><p>${m.placement_attempt_count||0} 次放置尝试 · ${m.failed_placement_count||0} 次偏离目标区域 · 整条${p.record.result==='completed'?'最终完成':'结果待检查'}</p><div class="sim-attempt-list">${events.map((v,i)=>`<button data-sim-quality="${i}" data-quality-state="${e(v.state)}"><span><b>${e(v.label)}</b><small>${n(v.start_s)}–${n(v.end_s)} s · ${e(p.segments.find(s=>s.id===v.segment_id)?.name||'区间待核对')}</small></span><span>${v.attempt?n(v.attempt.settled_xy_distance_m*100,1)+' cm':''} ↗</span></button>`).join('')||'<p>逐次放置结果待复核。</p>'}</div><details><summary>分段与质检方法</summary><p>${e(p.segmentation?.note||'')}</p><p>每次释放后独立观察物体位置和稳定窗口，保留各次尝试的时间区间与测量值。</p></details></section>`;
  }
  render(){
    const p=this.p,r=p.record,e=this.e,m=r.metrics,ref=this.index.records.find(r=>r.id===this.index.reference_id);
    const rows=[['time_per_m','单位搬运距离耗时','s/m',false],['path_efficiency','物体路径效率','%',true],['carry_low_fraction','搬运低速占比','%',true]];
    this.host.innerHTML=`<div class="sim-demo"><header class="sim-header"><div><div class="sim-eyebrow">G1 · 跨桌搬运入篮</div><h1>仿真参考对比</h1><p>真实仿真记录的位置与运动 · 演示建议，不替代正式验收</p></div><a href="#library">返回工作台 ↗</a></header>
      <div class="sim-controls"><label>当前记录<select id="sim-select">${this.index.records.map(x=>`<option value="${x.id}" ${x.id===r.id?'selected':''}>${e(x.name)} · ${x.demo_grade} ${labels[x.demo_grade]}</option>`).join('')}</select></label><button id="sim-reference">查看参考样本</button><button id="sim-long">查看长耗时样本</button><span>${this.index.records.length} 条采集 · ${this.index.reference_ids.length} 条演示参考</span></div>
      <div class="sim-layout"><section class="sim-card sim-view"><div class="sim-card-title"><b id="sim-world-status">世界坐标回放 · 加载模型…</b><div><button id="sim-view3d">三维</button><button id="sim-viewmap">俯视</button></div></div><div id="sim-world"></div><div id="sim-map" hidden>${this.mapHTML()}</div><div class="sim-legend"><span><i style="background:#79a8e7"></i>机器人基座</span><span><i style="background:#ea887a"></i>目标物体</span><span><i style="background:#e5b357"></i>需复核低速</span></div><p class="sim-caption">位置和姿态来自记录；G1 参考结构、桌子及篮筐外形用于示意，尚未核验资产尺寸。</p></section>
      <aside class="sim-side"><section class="sim-card"><div class="sim-card-title"><b>采集画面</b><span>缓存抽帧 · 2 Hz</span></div><img id="sim-image" alt="当前时刻的仿真采集画面"></section><section class="sim-card sim-verdict"><div><span>演示建议</span><strong class="sim-grade grade-${r.demo_grade}">${r.demo_grade}</strong><b>${labels[r.demo_grade]}</b></div><p>${e(r.demo_reason)}</p><small>依据每次放置过程与已测效率；最终成功不抹去失败尝试。几何代理不认证精确包含或完整安全。</small></section><div class="sim-kpis"><div><b>${n(m.active_duration_s,1)}<small>s</small></b><span>任务有效段用时</span></div><div><b>${n(m.transfer_distance_m)}<small>m</small></b><span>物体初始搬运距离</span></div><div><b>${n(m.base_path_m)}<small>m</small></b><span>基座累计路径</span></div><div><b>${m.low_speed_count}</b><span>低速停留区间</span></div></div></aside></div>
      <section class="sim-card sim-timeline"><div class="sim-transport"><button id="sim-play">▶ 播放</button><input id="sim-slider" type="range" min="0" max="${r.duration_s}" step="0.01" value="0" aria-label="回放时间"><span id="sim-time">0.00 / ${n(r.duration_s)} s</span><select id="sim-speed" aria-label="播放速度"><option value="1">1×</option><option value="2">2×</option><option value=".5">0.5×</option></select></div><div class="sim-phasebar">${p.segments.map(s=>`<button data-sim-seek="${s.start_s}" style="flex:${s.end_s-s.start_s};--phase:${s.quality==='issue'?'#dc8278':colors[s.stage]||'#858a97'}" title="${e(s.name)} ${n(s.start_s)}–${n(s.end_s)}s">${e(s.name)}${s.quality==='issue'?' · 问题':''}</button>`).join('')}</div><div class="sim-live"><span id="sim-phase"></span><span id="sim-coordinates"></span><span id="sim-live-speed"></span></div><div class="sim-speedplot">${this.chartHTML()}</div><small>速度曲线：基座水平速度。低速不直接等于无效停滞；系统回位不计入效率比较。</small></section>
      ${this.qualityHTML()}
      <div class="sim-bottom"><section class="sim-card"><div class="sim-card-title"><b>与参考区间对比</b><span>同任务 · 演示参考</span></div><table><thead><tr><th>指标</th><th>当前</th><th>参考 P10–P90</th></tr></thead><tbody>${rows.map(([key,label,unit,pct])=>{const v=m[key]*(pct?100:1),b=this.index.bands[key].map(v=>v*(pct?100:1));return `<tr><td>${label}</td><td>${n(v)} ${unit}</td><td>${n(b[0])}–${n(b[2])} ${unit}</td></tr>`}).join('')}</tbody></table><p>代表样本：${e(ref.name)}。参考区间由5条同任务完成记录形成。</p><details><summary>选择依据与适用范围</summary><p>${e(this.index.method)}</p><p>${e(this.index.note)}</p></details></section>
      <section class="sim-card"><div class="sim-card-title"><b>低速发生在哪里</b><span>点击定位画面与轨迹</span></div><div class="sim-events">${p.events.map((ev,i)=>`<button data-sim-event="${i}"><span><b>${n(ev.start_s)}–${n(ev.end_s)} s</b><small>${e(ev.label)} · ${n(ev.duration_s)} 秒</small></span><span>${ev.position_m.slice(0,2).map(v=>n(v)).join(', ')} m</span></button>`).join('')||'<p>当前阈值下没有持续低速区间。</p>'}</div><small>水平速度＜0.03 m/s、转向速度＜0.1 rad/s，连续≥0.7秒。位置为区间内基座坐标中位数。</small></section></div>
      <footer class="sim-footer">仿真世界坐标与关节状态 · 逐次事件与效率分析</footer></div>`;
    const $=s=>this.host.querySelector(s);
    $('#sim-select').onchange=ev=>this.select(ev.target.value);
    $('#sim-reference').onclick=()=>this.select(this.index.reference_id);
    $('#sim-long').onclick=()=>this.select(this.index.default_id);
    $('#sim-play').onclick=()=>{if(this.time>=r.duration_s)this.time=0;this.playing=!this.playing;this.last=performance.now();this.update();};
    $('#sim-slider').oninput=ev=>{this.time=Number(ev.target.value);this.update();};
    $('#sim-speed').onchange=ev=>this.speed=Number(ev.target.value);
    $('#sim-viewmap').onclick=()=>{$('#sim-map').hidden=false;$('#sim-world').hidden=true;this.update();};
    $('#sim-view3d').onclick=()=>{if(!this.view?.solid)return;$('#sim-map').hidden=true;$('#sim-world').hidden=false;this.view.resize();};
    this.host.querySelectorAll('[data-sim-event]').forEach(b=>b.onclick=()=>{this.time=p.events[Number(b.dataset.simEvent)].start_s;this.playing=false;this.update();});
    this.host.querySelectorAll('[data-sim-quality]').forEach(b=>b.onclick=()=>{this.time=Math.max(0,p.quality_events[Number(b.dataset.simQuality)].start_s-.5);this.playing=false;this.update();});
    this.host.querySelectorAll('[data-sim-seek]').forEach(b=>b.onclick=()=>{this.time=Number(b.dataset.simSeek);this.update();});
  }
  update(){
    if(this.closed||!this.p)return;
    const $=s=>this.host.querySelector(s),p=this.p,tr=p.trace;
    const i=Math.max(0,Math.min(tr.times_s.length-1,Math.floor(this.time/.1)));
    $('#sim-slider').value=this.time;$('#sim-time').textContent=`${n(this.time)} / ${n(p.record.duration_s)} s`;
    $('#sim-play').textContent=this.playing?'Ⅱ 暂停':'▶ 播放';
    $('#sim-phase').textContent=p.segments.find(s=>s.start_s<=this.time&&s.end_s>this.time)?.name||'记录结束';
    $('#sim-coordinates').textContent='基座 x / y / z：'+tr.base_m[i].map(v=>n(v)).join(' / ')+' m';
    $('#sim-live-speed').textContent='水平速度 '+n(tr.speed_m_s[i])+' m/s';
    for(const [id,key] of [['#sim-base-dot','base_m'],['#sim-target-dot','target_m']]){const [x,y]=this.mapPoint(tr[key][i]);$(id).setAttribute('cx',x);$(id).setAttribute('cy',y);}
    const x=this.time/p.record.duration_s*900;$('#sim-cursor').setAttribute('x1',x);$('#sim-cursor').setAttribute('x2',x);
    const frame=Math.floor(this.time*2);if(frame!==this.frameIndex){this.frameIndex=frame;$('#sim-image').src=`/api/task-audit/frame?ep=${p.record.id}&t=${Math.min(frame/2,p.record.duration_s).toFixed(2)}`;}
    if(this.view?.solid&&this.data)this.view.pose(Math.min(this.data.samples-1,Math.round(this.time*this.data.meta.timeline.rate_hz)));
  }
  tick(now){
    if(this.closed)return;
    if(this.playing){this.time=advancePlayback(this.time,now,this.last??now,this.speed,this.p.record.duration_s);if(this.time>=this.p.record.duration_s)this.playing=false;this.update();}
    this.last=now;this.raf=requestAnimationFrame(t=>this.tick(t));
  }
}
