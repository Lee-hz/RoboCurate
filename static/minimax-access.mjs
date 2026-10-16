// Keys live only in this form while editing; never use browser storage.
export function installMiniMaxAccess(api) {
  const dialog=document.createElement('dialog');dialog.className='minimax-dialog';
  dialog.setAttribute('aria-labelledby','minimax-title');
  dialog.innerHTML=`<form class="minimax-form">
    <header><div><h2 id="minimax-title">MiniMax 接入</h2><p id="minimax-status" role="status">正在读取…</p></div><button type="button" data-close aria-label="关闭 MiniMax 接入">×</button></header>
    <div class="minimax-model"><span>支持模型</span><strong>HORIZON-MiniMax</strong></div>
    <p class="minimax-note">请使用公司网关的接口地址及对应 API Key；内网接口需连接公司网络或 VPN。</p>
    <label>接口地址<input name="endpoint" type="url" required autocomplete="off" spellcheck="false" placeholder="https://你的网关/v1/chat/completions"></label>
    <label>API Key<input name="api_key" type="password" autocomplete="new-password" maxlength="8192" spellcheck="false" placeholder="填写自己的 API Key"></label>
    <p class="minimax-note" id="minimax-key-note">密钥仅保存到本机，不会随项目上传。</p>
    <p class="minimax-note">开始分析时会发送采样画面及所选反馈，并使用你的 API 额度。</p>
    <p class="minimax-error" role="alert"></p>
    <footer><button type="button" data-disconnect>断开接入</button><button type="submit" class="primary">保存接入</button></footer>
  </form>`;
  document.body.append(dialog);
  const form=dialog.querySelector('form'),endpoint=form.elements.endpoint,key=form.elements.api_key;
  const status=dialog.querySelector('#minimax-status'),error=dialog.querySelector('[role="alert"]');
  const disconnect=dialog.querySelector('[data-disconnect]'),trigger=document.querySelector('#minimax-access');
  let busy=false;
  function update(data){
    status.textContent=data.configured?(data.tested?'已连接 · 最近调用成功':'已保存 · 待首次调用验证'):'未接入';
    trigger.textContent=data.configured?'MiniMax · 已配置':'MiniMax 接入';
    endpoint.value=data.endpoint||'';key.value='';key.required=!data.has_key;
    key.placeholder=data.has_key?'已保存，留空保留原密钥':'填写自己的 API Key';
    dialog.querySelector('#minimax-key-note').textContent=data.has_key?'密钥不会回显。更换接口地址时需重新填写。':'密钥仅保存到本机，不会随项目上传。';
    disconnect.disabled=!data.configured;dialog.dataset.configured=String(data.configured);
  }
  function setBusy(value){busy=value;form.querySelectorAll('button,input').forEach(el=>el.disabled=value);if(!value)disconnect.disabled=dialog.dataset.configured!=='true';}
  async function open(){
    if(dialog.open)return;error.textContent='';key.value='';dialog.showModal();setBusy(true);
    try{update(await api('/api/taskflow/connection'));}catch(e){error.textContent=e.message;}
    finally{setBusy(false);endpoint.focus();}
  }
  async function change(body){
    setBusy(true);error.textContent='';
    try{update(await api('/api/taskflow/connection',body));document.dispatchEvent(new Event('minimax-connection-changed'));}
    catch(e){error.textContent=e.message;}
    finally{key.value='';setBusy(false);}
  }
  form.addEventListener('submit',e=>{e.preventDefault();if(!busy)change({action:'save',endpoint:endpoint.value.trim(),api_key:key.value});});
  disconnect.addEventListener('click',()=>{if(!busy)change({action:'disconnect'});});
  dialog.querySelector('[data-close]').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  dialog.addEventListener('close',()=>{key.value='';error.textContent='';});
  document.addEventListener('click',e=>{if(e.target.closest('[data-minimax-access]'))open();});
  api('/api/taskflow/connection').then(update).catch(()=>{});
  return {open};
}
