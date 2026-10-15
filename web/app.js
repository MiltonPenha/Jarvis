/* JARVIS HUD: one server channel, persistent task IDs, explicit audio controls. */
class JarvisHUD extends ReactorVisuals {
  constructor() {
    super();
    this.state = 'IDLE'; this.audioLevel = 0; this.speedFactor = 1;
    this.yaw = 0; this.pitch = .35; this.roll = .12;
    this.canvas = document.getElementById('arcCanvas');
    this.ctx = this.canvas.getContext('2d');
    this.eqContainer = document.getElementById('eq-bars');
    for (let i=0;i<28;i++) this.eqContainer.appendChild(document.createElement('div')).className='eq-bar';
    this.initSphereParticles(); this.startAnimationLoop();
    this.session = localStorage.getItem('jarvis-session') || crypto.randomUUID();
    localStorage.setItem('jarvis-session',this.session);
    this.activeTask = null; this.continuousMode = false; this.stopping = false;
    this.modelRequests = {};
    this.feed = document.getElementById('terminal-feed');
    this.feed.replaceChildren();
    this.bind(); this.clock(); this.connect();
    this.refreshHistory(); this.loadSettings();
    this.poll = setInterval(()=>this.reconcile(),4000);
  }
  async api(path,body) {
    const response = await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(40000)});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail==='string'?result.detail:'Não foi possível concluir o pedido.');
    return result;
  }
  async safe(fn) { try { await fn(); } catch(error) { this.addFeedEntry('SISTEMA',error.message);document.getElementById('panel-message').textContent=error.message; } }
  clock() {
    const update=()=>{
      const now=new Date();
      document.getElementById('hud-clock').textContent=now.toLocaleTimeString('pt-BR');
      document.getElementById('hud-date').textContent=now.toLocaleDateString('pt-BR');
    }; update(); setInterval(update,1000);
  }
  connect() {
    this.ws = new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws`);
    this.ws.onopen=()=>{this.setState('IDLE');this.reconcile();};
    this.ws.onmessage=e=>{try{this.message(JSON.parse(e.data));}catch(error){console.error(error);}};
    this.ws.onclose=()=>{this.setState('DISCONNECTED');if(!this.stopping)setTimeout(()=>this.connect(),2500);};
  }
  send(message) {
    if(this.ws?.readyState!==WebSocket.OPEN) throw new Error('Conexão indisponível. Aguarde a reconexão.');
    this.ws.send(JSON.stringify({...message,session:this.session}));
  }
  message(msg) {
    if(msg.session&&msg.session!==this.session)return;
    if(msg.type==='init'||msg.type==='telemetry')this.updateTelemetry(msg.telemetry||msg.data);
    if(msg.type==='state')this.setState(msg.state);
    if(msg.type==='audio_level')this.audioLevel=msg.level;
    if(msg.type==='audio_diagnostics'){
      const d=msg.data;
      document.getElementById('microphone-status').textContent=`Microfone: ${d.device||'indisponível'} · ${d.speech_detected?'fala detectada':'sem fala detectada'}`;
      document.getElementById('diagnostics').textContent=JSON.stringify({...this.settings,audio_capture:d,credentials:undefined},null,2);
    }
    if(msg.type==='user_command')this.addFeedEntry('VOCÊ',msg.text,true);
    if(msg.type==='jarvis_response')this.addFeedEntry('J.A.R.V.I.S.',msg.response);
    if(msg.type==='notice')this.addFeedEntry('SISTEMA',msg.text);
    if(msg.type==='tool'){
      const data=msg.data;
      document.getElementById('activity').textContent=`${data.action}: ${data.state}`;
      if(data.result?.sources) this.showSources(data.result.sources);
      if(data.result?.error)this.addFeedEntry('FERRAMENTA',data.result.error);
    }
    if(msg.type==='task_updated'){
      if(['queued','running','cancelling'].includes(msg.task.state))this.activeTask=msg.task.id;
      else if(this.activeTask===msg.task.id)this.activeTask=null;
      this.showTask(msg.task);
    }
    if(msg.type==='autostart_status')this.setAutostartStatus(msg.enabled);
  }
  async sendCommand(text) {
    text=text.trim(); if(!text)return;
    // Retain the request ID across a lost HTTP response or page reload. A retry
    // with the same text cannot accidentally execute an accepted request twice.
    let pending=null;
    try{pending=JSON.parse(sessionStorage.getItem('jarvis-pending-command')||'null');}catch(e){}
    const id=pending?.session===this.session&&pending?.text===text?pending.id:crypto.randomUUID();
    sessionStorage.setItem('jarvis-pending-command',JSON.stringify({session:this.session,text,id}));
    this.activeTask=id;
    const task=await this.api('command',{command:text,session:this.session,id});
    sessionStorage.removeItem('jarvis-pending-command');
    this.showTask(task); this.setState('PROCESSING');
  }
  setState(state) {
    this.state=state;
    const names={IDLE:'PRONTO',LISTENING:'ESCUTANDO',PROCESSING:'PROCESSANDO',EXECUTING:'EXECUTANDO FERRAMENTA',WAITING:'AGUARDANDO INFORMAÇÃO',SPEAKING:'FALANDO',COMPLETED:'CONCLUÍDO',CANCELLED:'CANCELADO',FAILED:'FALHOU',DISCONNECTED:'DESCONECTADO — RECONECTANDO'};
    document.getElementById('status-text').textContent=names[state]||state;
    document.getElementById('core-state').textContent=names[state]||state;
    document.getElementById('status-badge').className='status-indicator '+(['PROCESSING','EXECUTING'].includes(state)?'processing':state==='LISTENING'?'listening':'');
    document.getElementById('mic-trigger-btn').classList.toggle('active',state==='LISTENING');
    this.speedFactor=['PROCESSING','EXECUTING'].includes(state)?3:state==='SPEAKING'?2:1;
    if(['CANCELLED','FAILED'].includes(state)){
      this.continuousMode=false;document.getElementById('continuous-mic-cb').checked=false;
    }
  }
  updateEqBars() {
    [...this.eqContainer.children].forEach((bar,i)=>{
      const active=['LISTENING','SPEAKING'].includes(this.state);
      bar.style.height=`${active?4+this.audioLevel*30+(Math.sin(Date.now()/150+i*.4)+1)*8:4}px`;
    });
  }
  updateTelemetry(data) {
    if(!data)return;
    for(const name of ['cpu','ram','disk']){
      const percent=Math.round(data[name+'_percent']||0);
      document.getElementById(name+'-val').textContent=percent+'%';
      document.getElementById(name+'-gauge').style.strokeDashoffset=2*Math.PI*40*(1-percent/100);
    }
    document.getElementById('cpu-sub').textContent=`${data.cpu_cores} cores · ${data.cpu_ghz} GHz`;
    document.getElementById('ram-sub').textContent=`${data.ram_used_gb} / ${data.ram_total_gb} GB`;
    document.getElementById('disk-sub').textContent=`${data.disk_free_gb} GB livres`;
    document.getElementById('uptime-val').textContent=data.uptime;
    document.getElementById('host-val').textContent=data.hostname;
    if(data.autostart_enabled!==undefined)this.setAutostartStatus(data.autostart_enabled);
  }
  setAutostartStatus(enabled) {
    document.getElementById('autostart-dot').classList.toggle('active',enabled);
    document.getElementById('autostart-label').textContent=enabled?'BOOT: ATIVO':'BOOT: DESATIVADO';
  }
  addFeedEntry(sender,text,isUser=false) {
    const entry=document.createElement('div');entry.className='feed-entry '+(isUser?'user-msg':'jarvis-msg');
    const head=document.createElement('div');head.className='entry-header';
    const name=document.createElement('span');name.className='entry-sender';name.textContent=sender;
    const time=document.createElement('span');time.className='entry-time';time.textContent=new Date().toLocaleTimeString('pt-BR');head.append(name,time);
    const content=document.createElement('div');content.className='entry-content';content.textContent=text||'';
    entry.append(head,content);this.feed.append(entry);
    while(this.feed.children.length>150)this.feed.firstChild.remove();
    this.feed.scrollTop=this.feed.scrollHeight;
  }
  showSources(sources) {
    const box=document.getElementById('sources');box.replaceChildren();
    for(const source of sources){
      const item=document.createElement('p');item.textContent=`${source.path||source.title||''}${source.line?':'+source.line:''} — ${source.excerpt||''}`;
      if(source.url){try{const u=new URL(source.url);if(['http:','https:'].includes(u.protocol)){const a=document.createElement('a');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';a.textContent=' Abrir fonte';item.append(a);}}catch(e){}}
      box.append(item);
    }
  }
  showTask(task) {
    document.getElementById('activity').textContent=`Tarefa ${task.id.slice(0,8)} · ${task.state}`;
  }
  async reconcile() {
    await this.safe(async()=>{
      const {tasks}=await this.api('tasks?session='+encodeURIComponent(this.session));
      const running=tasks.find(t=>['queued','running','cancelling'].includes(t.state));
      if(running){this.activeTask=running.id;this.showTask(running);}
      else if(this.activeTask&&this.state!=='SPEAKING'){
        const recent=tasks.find(t=>t.id===this.activeTask);
        if(recent){this.showTask(recent);this.activeTask=null;this.setState(recent.state==='failed'?'FAILED':recent.state==='cancelled'?'CANCELLED':'COMPLETED');}
      }
    });
  }
  async refreshHistory() {
    await this.safe(async()=>{
      const result=await this.api('history?session='+encodeURIComponent(this.session));
      this.feed.replaceChildren();
      for(const msg of result.messages||[]){if(['user','assistant'].includes(msg.role)&&typeof msg.content==='string'&&msg.content)this.addFeedEntry(msg.role==='user'?'VOCÊ':'J.A.R.V.I.S.',msg.content,msg.role==='user');}
      if(!this.feed.children.length)this.addFeedEntry('J.A.R.V.I.S.','Interface pronta. Configure um provedor e modelo no painel para conversar. O microfone começa desligado.');
    });
  }
  async loadSettings() {
    await this.safe(async()=>{
      const s=await this.api('settings');this.settings=s;
      for(const key of ['provider','fallback_provider','tts_provider','tts_voice','stt_provider'])document.getElementById('setting-'+key).value=s[key];
      this.setModelOptions(false,[],s.model);
      this.setModelOptions(true,[],s.fallback_model);
      document.getElementById('setting-speech_enabled').checked=s.speech_enabled;
      document.getElementById('integration-status').textContent=`Hermes AIAgent · ${s.provider} / ${s.model||'modelo não escolhido'}`;
      document.getElementById('diagnostics').textContent=JSON.stringify({credentials:s.credentials,vault:s.vault,workspace_roots:s.workspace_roots,limits:s.limits},null,2);
      await Promise.all([this.loadModels(),this.loadModels(true),this.loadMicrophones(s)]);
    });
  }
  async loadMicrophones(s) {
    await this.safe(async()=>{
      const audio=await this.api('audio/devices');const select=document.getElementById('setting-input_device');
      select.replaceChildren();const system=document.createElement('option');system.value='';system.textContent='Padrão do Windows';select.append(system);
      for(const device of audio.inputs){const option=document.createElement('option');option.value=device.id;option.textContent=device.name+' · '+device.hostapi;select.append(option);}
      select.value=s.input_device||'';
      document.getElementById('microphone-status').textContent='Microfone selecionado: '+(audio.selected||'indisponível');
    });
  }
  setModelOptions(fallback,models,selected='') {
    const select=document.getElementById(fallback?'setting-fallback_model':'setting-model');
    select.replaceChildren();
    const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Selecione um modelo';select.append(placeholder);
    for(const model of [...new Set(selected?[selected,...models]:models)]){
      const option=document.createElement('option');option.value=model;
      option.textContent=model+(model===selected&&!models.includes(model)?' (configurado; acesso não confirmado)':'');select.append(option);
    }
    select.value=selected;
  }
  async loadModels(fallback=false) {
    const role=fallback?'fallback':'primary';
    const provider=document.getElementById(fallback?'setting-fallback_provider':'setting-provider').value;
    const select=document.getElementById(fallback?'setting-fallback_model':'setting-model');
    const status=document.getElementById(fallback?'fallback-models-status':'models-status');
    const request=this.modelRequests[role]=(this.modelRequests[role]||0)+1;
    const selected=select.value;
    select.disabled=true;
    if(!provider){this.setModelOptions(fallback,[]);status.textContent='Fallback desativado.';return;}
    status.textContent='Carregando modelos…';
    try{
      const result=await this.api('models?provider='+encodeURIComponent(provider));
      if(request!==this.modelRequests[role])return;
      this.setModelOptions(fallback,result.models,selected);
      status.textContent=result.models.length?`${result.models.length} modelos disponíveis. Abra a lista para escolher.`:'Nenhum modelo de conversa disponível para esta conta.';
    }catch(error){
      if(request!==this.modelRequests[role])return;
      this.setModelOptions(fallback,[],selected);status.textContent=error.message;
    }finally{if(request===this.modelRequests[role])select.disabled=false;}
  }
  async showMemory() {
    const memory=await this.api('memory');const box=document.getElementById('memory-list');box.replaceChildren();
    for(const target of ['user','memory'])for(const text of memory[target]||[]){
      const row=document.createElement('div');row.className='memory-row';
      const input=document.createElement('textarea');input.value=text;input.setAttribute('aria-label','Memória '+target);
      const save=document.createElement('button');save.textContent='Corrigir';save.onclick=()=>this.safe(async()=>{const r=await this.api('memory',{action:'memory_patch',target,old_text:text,content:input.value});if(r.error)throw new Error(r.error);await this.showMemory();});
      const del=document.createElement('button');del.textContent='Excluir';del.onclick=()=>this.safe(async()=>{const r=await this.api('memory',{action:'memory_remove',target,old_text:text});if(r.error)throw new Error(r.error);await this.showMemory();});
      row.append(input,save,del);box.append(row);
    }
    if(!box.children.length)box.textContent='Nenhuma memória essencial registrada no Hermes.';
  }
  async showTasks() {
    const {tasks}=await this.api('tasks');const box=document.getElementById('task-list');box.replaceChildren();
    for(const task of tasks){
      const row=document.createElement('details');const title=document.createElement('summary');title.textContent=`${task.state} · ${task.prompt.slice(0,100)}`;
      const info=document.createElement('pre');info.textContent='Abra para consultar resultados e checkpoints.';row.append(title,info);
      row.ontoggle=()=>{if(row.open)this.safe(async()=>{info.textContent=JSON.stringify(await this.api('tasks/'+task.id),null,2);});};
      const open=document.createElement('button');open.textContent='Abrir conversa';open.onclick=()=>this.safe(async()=>{this.session=task.session;this.activeTask=null;localStorage.setItem('jarvis-session',this.session);await this.refreshHistory();document.getElementById('control-panel').close();});row.append(open);
      if(['queued','running','cancelling'].includes(task.state)){const cancel=document.createElement('button');cancel.textContent='Cancelar tarefa';cancel.onclick=()=>this.safe(async()=>{await this.api('tasks/'+task.id+'/cancel',{});await this.showTasks();});row.append(cancel);}
      if(['failed','interrupted','cancelled'].includes(task.state)){const resume=document.createElement('button');resume.textContent='Retomar com checkpoints';resume.onclick=()=>this.safe(async()=>{await this.api('tasks/'+task.id+'/resume',{});await this.showTasks();});row.append(resume);}
      box.append(row);
    }
  }
  bind() {
    const on=(id,fn)=>document.getElementById(id).addEventListener('click',()=>this.safe(fn));
    document.getElementById('command-form').onsubmit=e=>{e.preventDefault();const input=document.getElementById('cmd-input');const text=input.value;this.safe(async()=>{await this.sendCommand(text);input.value='';});};
    on('mic-trigger-btn',async()=>{if(this.state==='LISTENING'){this.send({action:'microphone_off'});this.setState('IDLE');}else this.send({action:'listen_trigger'});});
    document.getElementById('continuous-mic-cb').onchange=e=>{this.continuousMode=e.target.checked;this.safe(async()=>this.send({action:this.continuousMode?'listen_trigger':'microphone_off',continuous:this.continuousMode}));};
    on('cancel-task-btn',async()=>{await this.api('audio/stop',{});if(this.activeTask)await this.api('tasks/'+this.activeTask+'/cancel',{});this.setState('CANCELLED');});
    on('mute-btn',async()=>{await this.api('audio/stop',{});this.continuousMode=false;document.getElementById('continuous-mic-cb').checked=false;this.setState('IDLE');});
    on('autostart-btn',async()=>{const r=await this.api('autostart/toggle',{});this.setAutostartStatus(r.enabled);this.addFeedEntry('SISTEMA',r.message);});
    on('stop-jarvis-btn',async()=>{this.stopping=true;await this.api('shutdown',{});this.setState('CANCELLED');});
    on('clear-log-btn',async()=>this.feed.replaceChildren());
    on('history-btn',async()=>this.refreshHistory());
    on('new-session-btn',async()=>{this.session=crypto.randomUUID();this.activeTask=null;localStorage.setItem('jarvis-session',this.session);await this.refreshHistory();});
    on('control-panel-btn',async()=>{document.getElementById('control-panel').showModal();await this.loadSettings();});
    on('close-panel',async()=>document.getElementById('control-panel').close());
    on('save-settings',async()=>{
      const data={};for(const key of ['provider','model','fallback_provider','fallback_model','tts_provider','tts_voice','stt_provider','input_device'])data[key]=document.getElementById('setting-'+key).value;
      data.speech_enabled=document.getElementById('setting-speech_enabled').checked;
      await this.api('settings',data);await this.loadSettings();document.getElementById('panel-message').textContent='Configurações salvas e verificadas.';
    });
    on('discover-models',async()=>{await Promise.all([this.loadModels(),this.loadModels(true)]);});
    for(const fallback of [false,true])document.getElementById(fallback?'setting-fallback_provider':'setting-provider').onchange=()=>this.safe(async()=>{this.setModelOptions(fallback,[]);await this.loadModels(fallback);});
    on('memory-refresh',async()=>this.showMemory());
    on('memory-events-refresh',async()=>{document.getElementById('memory-events').textContent=JSON.stringify(await this.api('memory/events'),null,2);});
    on('memory-add',async()=>{const input=document.getElementById('new-memory');const r=await this.api('memory',{action:'memory_add',content:input.value});if(r.error)throw new Error(r.error);input.value='';await this.showMemory();});
    on('tasks-refresh',async()=>this.showTasks());
    on('usage-refresh',async()=>{document.getElementById('usage').textContent=JSON.stringify(await this.api('usage'),null,2);});
    on('vault-search',async()=>{const r=await this.api('vault/search?q='+encodeURIComponent(document.getElementById('vault-query').value));this.showSources(r.sources);const box=document.getElementById('vault-results');box.replaceChildren();for(const source of r.sources){const b=document.createElement('button');b.textContent=source.path+':'+source.line;b.onclick=()=>this.safe(async()=>{const note=await this.api('vault/note?path='+encodeURIComponent(source.path));document.getElementById('note-path').value=source.path;document.getElementById('note-content').value=note.content;this.noteHash=note.sha256;document.getElementById('vault-save').disabled=note.truncated;});box.append(b);}});
    on('vault-save',async()=>{await this.api('vault/note',{path:document.getElementById('note-path').value,content:document.getElementById('note-content').value,expected_hash:this.noteHash||null});document.getElementById('panel-message').textContent='Nota gravada e verificada.';this.noteHash=null;});
    document.getElementById('note-path').oninput=()=>{this.noteHash=null;document.getElementById('vault-save').disabled=false;};
    for(const button of document.querySelectorAll('[data-cmd],[data-action]'))button.onclick=()=>this.safe(async()=>{
      if(button.dataset.action){const result=await this.api('actions',{action:button.dataset.action,session:this.session,id:crypto.randomUUID()});this.showTask(result);}
      else await this.sendCommand(button.dataset.cmd);
    });
  }
}
window.addEventListener('DOMContentLoaded',()=>{window.jarvis=new JarvisHUD();});
