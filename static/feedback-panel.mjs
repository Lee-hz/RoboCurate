const channelNames={'state.q':'身体关节','hand.left.state_q':'左手手指','hand.right.state_q':'右手手指','imu.gyro':'身体角速度'};
export function jointLabel(name){return name.replace(/_joint$/,'').replace(/left/g,'左').replace(/right/g,'右').replace(/shoulder/g,'肩').replace(/elbow/g,'肘').replace(/wrist/g,'腕').replace(/hip/g,'髋').replace(/knee/g,'膝').replace(/ankle/g,'踝').replace(/waist/g,'腰').replace(/pitch/g,'俯仰').replace(/roll/g,'横滚').replace(/yaw/g,'旋转').replace(/index/g,'食指').replace(/middle/g,'中指').replace(/ring/g,'无名指').replace(/pinky/g,'小指').replace(/thumb/g,'拇指').replace(/aux/g,'辅助').replaceAll('_',' ');}
export function feedbackSample(data,key,column,time){
  const index=Math.floor(Math.max(0,time)*data.rate_hz+1e-8),channel=data.channels.find(c=>c.key===key);
  // Never carry the last sample across a missing or out-of-range observation.
  const value=channel?.values[index]?.[column];
  return {time:data.times_s[index],value:typeof value==='number'&&Number.isFinite(value)?value:null};
}
export function relatedRequests(manifest,segment){return (manifest?.requests||[]).filter(r=>!r.range||r.range.start_s<segment.end_s&&r.range.end_s>segment.start_s);}

export class FeedbackPanel {
  constructor(owner,host){this.owner=owner;this.host=host;this.alive=true;this.key='state.q';this.column=0;}
  async load(){
    const o=this.owner;
    if(o.asset.source.kind!=='recording'||o.asset.id==='pending-recording'){this.host.innerHTML='<p class="tf-note">机器人反馈需关联已解析的采集记录。</p>';return;}
    this.host.innerHTML='<p class="tf-note">正在读取关节、手部与 IMU 反馈…</p>';
    try{
      const data=await o.api('/api/taskflow/feedback?id='+o.asset.id);if(!this.alive)return;
      if(!data.available){this.host.innerHTML=`<p class="tf-note">${o.e(data.reason||'没有可用反馈')}</p>`;return;}
      this.data=data;this.key=data.channels.find(c=>c.key==='state.q')?.key||data.channels[0].key;
      this.column=Math.max(0,this.channel().names.findIndex(n=>/^right_elbow(?:_joint)?$/.test(n)));
      this.render();
    }catch(err){if(this.alive){this.host.innerHTML=`<p class="tf-note">反馈暂不可用：${o.e(err.message)}</p><button type="button">重新读取反馈</button>`;this.host.querySelector('button').onclick=()=>this.load();}}
  }
  channel(){return this.data.channels.find(c=>c.key===this.key);}
  render(){
    const o=this.owner,e=o.e,c=this.channel(),unit=c.unit==='0=open 1=closed'?'闭合量 0–1':c.unit;
    this.host.innerHTML=`<div class="tf-feedback-heading"><h3>机器人反馈</h3><span class="tf-feedback-reading" aria-label="当前反馈读数"></span></div><div class="tf-feedback-controls"><select aria-label="反馈通道">${this.data.channels.map(ch=>`<option value="${e(ch.key)}" ${ch.key===this.key?'selected':''}>${e(channelNames[ch.key]||ch.key)} · ${ch.names.length} 维</option>`).join('')}</select><select aria-label="关节或分量">${c.names.map((n,i)=>`<option value="${i}" ${i===this.column?'selected':''}>${e(jointLabel(n))}</option>`).join('')}</select><span>${e(unit)}</span></div><button type="button" class="tf-feedback-chart" aria-label="反馈曲线，点击定位录像；左右键移动零点一秒"><svg viewBox="0 0 700 92" preserveAspectRatio="none" aria-hidden="true"></svg></button><div class="tf-feedback-scale"><span>0.0s</span><span>点击定位</span><span>${o.asset.duration_s.toFixed(1)}s</span></div><details class="tf-feedback-source"><summary>数据说明</summary><p class="tf-note">${this.data.source==='native_feedback'?'实测反馈，20 Hz 因果对齐':'历史重采样快照'} · 空缺表示无有效读数。逐值曲线供本机核对，模型收到的摘要见「模型输入」。浅色区表示当前阶段。</p></details>`;
    const selects=this.host.querySelectorAll('select');
    selects[0].onchange=ev=>{this.key=ev.target.value;this.column=0;this.render();};
    selects[1].onchange=ev=>{this.column=Number(ev.target.value);this.render();};
    const svg=this.host.querySelector('svg'),values=c.values.map(v=>v[this.column]),good=values.filter(v=>v!==null&&Number.isFinite(v));
    const min=good.length?good.reduce((a,b)=>Math.min(a,b),Infinity):0,max=good.length?good.reduce((a,b)=>Math.max(a,b),-Infinity):1,span=max-min||1;
    let path='',pen=false;values.forEach((v,i)=>{if(v===null||!Number.isFinite(v)){pen=false;return;}path+=(pen?'L':'M')+(700*this.data.times_s[i]/o.asset.duration_s).toFixed(2)+','+(76-60*(v-min)/span).toFixed(2);pen=true;});
    svg.innerHTML=`<rect class="tf-feedback-stage" y="0" height="92"/><path d="${path}" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke"/><text x="4" y="10">${max.toFixed(3)}</text><text x="4" y="90">${min.toFixed(3)}</text><line class="tf-feedback-cursor" y1="0" y2="92"/>`;
    const chart=this.host.querySelector('.tf-feedback-chart');
    chart.onclick=ev=>{const box=chart.getBoundingClientRect();o.stop();o.seek(ev.detail===0?o.time:Math.max(0,Math.min(1,(ev.clientX-box.left)/box.width))*o.asset.duration_s);};
    chart.onkeydown=ev=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(ev.key)){ev.preventDefault();o.stop();o.seek(ev.key==='Home'?0:ev.key==='End'?o.asset.duration_s:Math.max(0,Math.min(o.asset.duration_s,o.time+(ev.key==='ArrowRight'?.1:-.1))));}};
    this.update(o.time||0);
  }
  update(time){
    if(!this.data||!this.alive)return;
    const sample=feedbackSample(this.data,this.key,this.column,time),unit=this.channel().unit;
    const label=this.host.querySelector('.tf-feedback-reading');if(!label)return;
    label.textContent=sample.value===null?'无有效读数':`${sample.value.toFixed(3)} ${unit==='0=open 1=closed'?'':unit} · ${sample.time.toFixed(2)}s`;
    const cursor=this.host.querySelector('.tf-feedback-cursor'),x=700*time/this.owner.asset.duration_s;cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);
    const segment=this.owner.run.result.segments[this.owner.segmentIndex],rect=this.host.querySelector('.tf-feedback-stage');rect.setAttribute('x',segment?700*segment.start_s/this.owner.asset.duration_s:0);rect.setAttribute('width',segment?700*(segment.end_s-segment.start_s)/this.owner.asset.duration_s:0);
  }
  destroy(){this.alive=false;}
}
