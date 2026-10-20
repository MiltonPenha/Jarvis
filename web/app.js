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
    this.voiceRequest = null;this.finishedTasks=new Set();
    this.modelRequests = {};
    this.feed = document.getElementById('terminal-feed');
    this.feed.replaceChildren();
    this.bind(); this.clock(); this.connect();
    this.refreshHistory(); this.loadSettings();
    this.poll = setInterval(()=>this.reconcile(),4000);
  }
  refreshSession() {
    if(!this.sessionRefresh)this.sessionRefresh=(async()=>{
      try{
        const response=await fetch('/',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000)});
        if(!response.ok)throw new Error('Não foi possível renovar o acesso local.');
      }catch(cause){throw Object.assign(new Error('Não consegui renovar a conexão local. Recarregue o painel quando o servidor estiver disponível.'),{code:'LOCAL_SESSION',cause});}
    })().finally(()=>{this.sessionRefresh=null;});
    return this.sessionRefresh;
  }
  async api(path,body) {
    const request=()=>fetch('/api/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(40000)});
    let response=await request(),result=await response.json();
    const expired=()=>response.status===403&&result.detail==='Abra a interface local primeiro.';
    // This exact middleware rejection happens before a handler/effect runs.
    // Retry it once after renewing the cookie; never replay other failures.
    if(expired()){
      await this.refreshSession();response=await request();result=await response.json();
    }
    if(expired())throw Object.assign(new Error('O acesso local não pôde ser renovado. Recarregue o painel.'),{code:'LOCAL_SESSION'});
    if (!response.ok) throw new Error(typeof result.detail==='string'?result.detail:'Não foi possível concluir o pedido.');
    this.sessionErrorShown=false;
    return result;
  }
  reportError(error) {
    if(error.code==='LOCAL_SESSION'&&this.sessionErrorShown)return;
    if(error.code==='LOCAL_SESSION')this.sessionErrorShown=true;
    this.addFeedEntry('SISTEMA',error.message);document.getElementById('panel-message').textContent=error.message;
  }
  async safe(fn) { try { await fn(); } catch(error) { this.reportError(error); } }
  clock() {
    const update=()=>{
      const now=new Date();
      document.getElementById('hud-clock').textContent=now.toLocaleTimeString('pt-BR');
      document.getElementById('hud-date').textContent=now.toLocaleDateString('pt-BR');
    }; update(); setInterval(update,1000);
  }
  async connect() {
    if(this.connecting||this.stopping)return;
    this.connecting=true;
    try{await this.refreshSession();}
    catch(error){this.connecting=false;this.setState('DISCONNECTED');this.reportError(error);this.scheduleReconnect();return;}
    this.connecting=false;
    if(this.stopping)return;
    this.ws = new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws`);
    this.ws.onopen=()=>{this.setState('IDLE');this.reconcile();};
    this.ws.onmessage=e=>{try{this.message(JSON.parse(e.data));}catch(error){console.error(error);}};
    this.ws.onclose=()=>{this.setState('DISCONNECTED');this.scheduleReconnect();};
  }
  scheduleReconnect() {
    if(!this.stopping&&!this.reconnectTimer)this.reconnectTimer=setTimeout(()=>{this.reconnectTimer=null;this.connect();},2500);
  }
  send(message) {
    if(this.ws?.readyState!==WebSocket.OPEN) throw new Error('Conexão indisponível. Aguarde a reconexão.');
    this.ws.send(JSON.stringify({...message,session:this.session}));
  }
  message(msg) {
    if(msg.session&&msg.session!==this.session)return;
    if(msg.task_id&&['state','progress','tool','jarvis_response','speech','notice','user_command'].includes(msg.type)&&
      (this.activeTask&&this.activeTask!==msg.task_id||this.finishedTasks?.has(msg.task_id)))return;
    if(msg.voice_request_id&&this.voiceRequest&&msg.voice_request_id!==this.voiceRequest)return;
    if(msg.type==='init'||msg.type==='telemetry')this.updateTelemetry(msg.telemetry||msg.data);
    if(msg.type==='state'&&msg.state!=='SPEAKING')this.setState(msg.state);
    if(msg.type==='speech')this.showSpeech(msg.data);
    if(msg.presentation)this.showContent(msg.presentation);
    if(msg.type==='audio_level')this.audioLevel=msg.level;
    if(msg.type==='voice_finished')this.voiceRequest=null;
    if(msg.type==='transcription'){
      this.text('recognized-request',msg.original||msg.text||msg.normalized||'');
      this.text('transcript-kind',msg.final?'Transcrição final':'Transcrição parcial · pode mudar');
      const field=document.getElementById('voice-transcript');
      if(field)field.textContent=`Original: ${msg.original}\nInterpretado: ${msg.normalized}`;
    }
    if(msg.type==='audio_diagnostics'){
      const d=msg.data;
      document.getElementById('microphone-status').textContent=`Microfone: ${d.device||'indisponível'} · ${d.speech_detected?'fala detectada':'sem fala detectada'}`;
      document.getElementById('diagnostics').textContent=JSON.stringify({...this.settings,audio_capture:d,credentials:undefined},null,2);
    }
    if(msg.type==='user_command'){
      if(!this.activeTask&&msg.task_id)this.activeTask=msg.task_id;
      if(msg.task_id&&this.contentTask!==msg.task_id){this.clearContent();this.contentTask=msg.task_id;}
      this.text('recognized-request',msg.text);this.text('transcript-kind',msg.source==='voice'?'Transcrição final':msg.source==='voice_preview'?'Comparação de voz':msg.source==='text'?'Pedido digitado':'Pedido recebido');
      this.addFeedEntry('VOCÊ',msg.text,true);
    }
    if(msg.type==='jarvis_response'){
      this.responses??=new Set();
      if(!this.responses.has(msg.task_id)){this.addFeedEntry('J.A.R.V.I.S.',msg.response);this.responses.add(msg.task_id);}
      if(msg.meta?.outcome==='clarification')this.setState('WAITING');
    }
    if(msg.type==='notice')this.addFeedEntry('SISTEMA',msg.text);
    if(msg.type==='progress'&&msg.data?.message)this.text('activity',msg.data.message);
    if(msg.type==='reminder_due')this.showReminderAlert(msg.reminder);
    if(msg.type==='tool'){
      const data=msg.data;
      document.getElementById('activity').textContent=`${data.action}: ${data.state}`;
      if(data.result?.sources) this.showSources(data.result.sources);
    }
    if(msg.type==='task_updated'){
      if(msg.task.input?.superseded_by)return;
      if(this.activeTask&&this.activeTask!==msg.task.id){
        if(!['queued','running','cancelling'].includes(msg.task.state))this.finishedTasks?.add(msg.task.id);
        return;
      }
      if(['queued','running','cancelling'].includes(msg.task.state))this.activeTask=msg.task.id;
      else {this.finishedTasks?.add(msg.task.id);if(this.activeTask===msg.task.id)this.activeTask=null;}
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
    let task;
    try{task=await this.api('command',{command:text,session:this.session,id});}
    catch(error){if(this.activeTask===id)this.activeTask=null;this.setState('FAILED');throw error;}
    sessionStorage.removeItem('jarvis-pending-command');
    this.showTask(task); this.setState('PROCESSING');
  }
  startListening(continuous=false) {
    if(this.voiceRequest){this.addFeedEntry('SISTEMA','O pedido de microfone já foi recebido. Aguarde ESCUTANDO ou use Interromper.');return;}
    this.voiceRequest=crypto.randomUUID();
    try{this.send({action:'listen_trigger',continuous,id:this.voiceRequest});}
    catch(error){this.voiceRequest=null;throw error;}
  }
  setState(state) {
    if(this.stateRendered===state)return;
    this.stateRendered=state;
    this.state=state;
    const names={IDLE:'PRONTO',LISTENING:'ESCUTANDO',PROCESSING:'PROCESSANDO',EXECUTING:'EXECUTANDO FERRAMENTA',WAITING:'AGUARDANDO INFORMAÇÃO',SPEAKING:'FALANDO',COMPLETED:'CONCLUÍDO',CANCELLED:'CANCELADO',FAILED:'FALHOU',DISCONNECTED:'DESCONECTADO — RECONECTANDO'};
    document.getElementById('status-text').textContent=names[state]||state;
    document.getElementById('core-state').textContent=names[state]||state;
    this.text('request-phase',names[state]||state);
    document.getElementById('status-badge').className='status-indicator '+(['PROCESSING','EXECUTING'].includes(state)?'processing':state==='LISTENING'?'listening':'');
    document.getElementById('mic-trigger-btn').classList.toggle('active',state==='LISTENING');
    this.speedFactor=['PROCESSING','EXECUTING'].includes(state)?3:state==='SPEAKING'?2:1;
    if(['CANCELLED','FAILED'].includes(state)){
      this.continuousMode=false;document.getElementById('continuous-mic-cb').checked=false;
    }
  }
  updateEqBars() {
    [...this.eqContainer.children].forEach((bar,i)=>{
      const active=this.state==='LISTENING'||this.speechPhase==='playing';
      bar.style.height=`${active?4+this.audioLevel*30+(Math.sin(Date.now()/150+i*.4)+1)*8:4}px`;
    });
  }
  updateTelemetry(data) {
    if(!data)return;
    for(const name of ['cpu','ram','disk']){
      const percent=Math.round(data[name+'_percent']||0);
      this.text(name+'-val',percent+'%');
    }
    document.getElementById('cpu-sub').textContent=`${data.cpu_cores} cores · ${data.cpu_ghz} GHz`;
    document.getElementById('ram-sub').textContent=`${data.ram_used_gb} / ${data.ram_total_gb} GB`;
    this.text('disk-sub',`${data.disk_free_gb} GB livres / ${data.disk_total_gb??'—'} GB`);
    document.getElementById('uptime-val').textContent=data.uptime;
    document.getElementById('host-val').textContent=data.hostname;
    if(data.autostart_enabled!==undefined)this.setAutostartStatus(data.autostart_enabled);
  }
  setAutostartStatus(enabled) {
    document.getElementById('autostart-dot').classList.toggle('active',enabled);
    document.getElementById('autostart-label').textContent=enabled?'BOOT: ATIVO':'BOOT: DESATIVADO';
  }
  addFeedEntry(sender,text,isUser=false) {
    const follow=this.feed.scrollHeight-this.feed.scrollTop-this.feed.clientHeight<64;
    const entry=document.createElement('div');entry.className='feed-entry '+(isUser?'user-msg':'jarvis-msg');
    if(isUser){
      for(const previous of this.feed.querySelectorAll('.current-request'))previous.classList.remove('current-request');
      entry.classList.add('current-request');
    }
    const head=document.createElement('div');head.className='entry-header';
    const name=document.createElement('span');name.className='entry-sender';name.textContent=sender;
    const time=document.createElement('span');time.className='entry-time';time.textContent=new Date().toLocaleTimeString('pt-BR');head.append(name,time);
    const content=document.createElement('div');content.className='entry-content';content.textContent=text||'';
    entry.append(head,content);this.feed.append(entry);
    while(this.feed.children.length>150)this.feed.firstChild.remove();
    if(follow)this.feed.scrollTop=this.feed.scrollHeight;
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
    if(task.input?.superseded_by)return;
    if(this.contentTask!==task.id){this.clearContent();this.contentTask=task.id;}
    if(task.input?.source)this.text('transcript-kind',task.input.source==='voice'?'Transcrição final':task.input.source==='voice_preview'?'Comparação de voz':'Pedido digitado');
    if(this.activityTask!==task.id||!['queued','running','cancelling'].includes(task.state))this.text('activity',`Tarefa ${task.id.slice(0,8)} · ${task.state}`);
    this.activityTask=task.id;
    if(task.input?.presentation)this.showContent(task.input.presentation);
    if(task.input?.final_feedback?.outcome==='clarification')this.setState('WAITING');
    else if(task.input?.final_feedback&&['completed','failed','cancelled'].includes(task.state))this.setState(task.state.toUpperCase());
    if(this.previewTask===task.id&&!['queued','running','cancelling'].includes(task.state)){
      const speech=task.input?.speech_result||{};
      this.text('voice-preview-status',speech.delivered?`Concluído · geração ${speech.generation_seconds}s · áudio ${speech.audio_seconds}s · ${speech.sample_rate} Hz`:speech.error||'Comparação interrompida.');
      document.getElementById('voice-preview-stop').disabled=true;this.previewTask=null;
    }
  }
  text(id,value) {const element=document.getElementById(id);if(element&&element.textContent!==String(value))element.textContent=value;}
  showSpeech(data={}) {
    this.speechPhase=data.phase;
    const labels={queued:'Na fila',generating:'Gerando áudio',playing:'Falando',completed:'Fala concluída',cancelled:'Fala interrompida',suppressed:'Fala substituída',failed:'Voz indisponível',timeout:'Tempo limite',disabled:'Desativada',busy:'Saída ocupada'};
    this.text('speech-phase',labels[data.phase]||data.phase||'Em espera');
    this.text('speech-detail',data.error||(data.phase==='generating'?`Geração local${data.chunks?' · trecho '+data.chunk+' de '+data.chunks:''}. O pedido permanece na tela.`:data.phase==='playing'?`Reprodução local · ${data.audio_seconds||'—'} s · microfone reservado.`:data.phase==='queued'?'Aguardando a saída de áudio.':'Saída de voz liberada.'));
  }
  showContent(data) {
    if(data.request_id&&this.activeTask&&data.request_id!==this.activeTask)return;
    const stages={searching:'Atualizando pesquisa',found:'Resultados disponíveis',selected:'Selecionado',opening:'Abrindo',sent:'Solicitado ao Windows',confirmed:'Confirmado',awaiting_choice:'Aguardando escolha',unconfirmed:'Execução não confirmada'};
    this.text('content-phase',stages[data.stage]||data.stage);this.text('content-title',data.title||'');
    this.text('content-channel',data.channel||(data.count!==undefined?data.count+' resultados legíveis':''));
    this.text('content-origin',(data.source_task_id&&data.request_id&&data.source_task_id!==data.request_id?'Pesquisa anterior · ':'')+(data.query?'Consulta: '+data.query:''));
    if(data.candidates!==undefined){
      const key=JSON.stringify([data.result_set_id,data.candidates]);
      if(key!==this.contentListKey){
        const list=document.getElementById('content-options');list?.replaceChildren();
        for(const candidate of data.candidates){const item=document.createElement('li');item.value=candidate.position;item.textContent=candidate.title+(candidate.channel?' · '+candidate.channel:'');list?.append(item);}
        this.contentListKey=key;
      }
    }
    const panel=document.getElementById('task-content');
    if(panel){
      const first=!panel.classList.contains('has-content');
      panel.classList.add('has-content');
      if(first)panel.open=true;
    }
  }
  clearContent() {
    this.text('content-phase','Sem conteúdo');this.text('content-title','O conteúdo aparece aqui quando houver uma seleção.');this.text('content-channel','');
    this.text('content-origin','');document.getElementById('content-options')?.replaceChildren();this.contentListKey=null;
    const panel=document.getElementById('task-content');
    if(panel){panel.classList.remove('has-content');panel.open=false;}
  }
  showMedia(data) {
    const names={playing:'Player em reprodução',buffering:'Carregando mídia',paused:'Pausada',ended:'Terminada',closed:'Aba fechada',unavailable:'Sem player vinculado',refreshing:'Atualização pendente'};
    this.text('media-phase',names[data.state]||'Sem observação');
    if(data.observed)this.text('media-title',(data.title||'')+(data.exists?' · '+Math.round(data.volume*100)+'%'+(data.muted?' · sem som':''):''));
    if(data.observed||data.state==='unavailable')document.getElementById('task-content')?.classList.toggle('has-media',!!data.exists&&!!data.observed);
  }
  async reconcile() {
    if(this.reconciling)return;
    this.reconciling=true;
    try{await this.safe(async()=>{
      const reminders=await this.api('reminders');
      const due=reminders.reminders.find(item=>item.state==='due');
      if(due)this.showReminderAlert(due);
      else document.getElementById('reminder-alert').hidden=true;
      const {tasks}=await this.api('tasks?session='+encodeURIComponent(this.session));
      const latest=tasks[0];
      if(latest&&this.observedRevision!==latest.id+latest.updated){
        const full=await this.api('tasks/'+latest.id);
        if(!this.activeTask||this.activeTask===full.id){
          this.showTask(full);this.text('recognized-request',full.input?.original_transcription||full.prompt);
          if(full.input?.speech_progress)this.showSpeech(full.input.speech_progress);
          else if(full.input?.speech_result)this.showSpeech({phase:full.input.speech_result.state,...full.input.speech_result});
          this.observedRevision=latest.id+latest.updated;
        }
      }
      if(!document.hidden)this.showMedia(await this.api('media/status?session='+encodeURIComponent(this.session)));
      const running=tasks.find(t=>['queued','running','cancelling'].includes(t.state));
      if(running){this.activeTask=running.id;this.showTask(running);}
      else if(this.activeTask&&this.state!=='SPEAKING'){
        const recent=tasks.find(t=>t.id===this.activeTask);
        if(recent){const full=await this.api('tasks/'+recent.id);this.showTask(full);this.activeTask=null;this.setState(full.input?.final_feedback?.outcome==='clarification'?'WAITING':recent.state==='failed'?'FAILED':recent.state==='cancelled'?'CANCELLED':'COMPLETED');}
      }
    });}finally{this.reconciling=false;}
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
      if(document.getElementById('browser-profile'))await this.loadBrowser();
      if(s.provider==='local-cpu')document.getElementById('panel-message').textContent='Modo local: sem chave de IA. Tempo e navegação usam internet; alarmes precisam do JARVIS aberto e do PC acordado.';
      for(const key of ['provider','fallback_provider','tts_provider','tts_voice','stt_provider'])document.getElementById('setting-'+key).value=s[key];
      if(document.getElementById('setting-voice_busy_policy'))document.getElementById('setting-voice_busy_policy').value=s.voice_busy_policy||'wait';
      if(document.getElementById('setting-piper_profile'))document.getElementById('setting-piper_profile').value=s.piper_profile||'original';
      this.updateVoiceFields();
      this.setModelOptions(false,[],s.model);
      this.setModelOptions(true,[],s.fallback_model);
      document.getElementById('setting-speech_enabled').checked=s.speech_enabled;
      document.getElementById('integration-status').textContent=`${s.provider==='local-cpu'?'JARVIS local · CPU':'Hermes AIAgent'} · ${s.provider} / ${s.model||'modelo não escolhido'}`;
      document.getElementById('diagnostics').textContent=JSON.stringify({local_model:s.local_model,credentials:s.credentials,vault:s.vault,workspace_roots:s.workspace_roots,limits:s.limits},null,2);
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
  updateVoiceFields() {
    const qwen=document.getElementById('qwen-voice-status');
    qwen.hidden=document.getElementById('setting-tts_provider').value!=='qwen-local';
    if(!qwen.hidden)qwen.textContent='Voz recriada localmente a partir da amostra JARVIS escolhida. Usa CPU e RAM do sistema, sem GPU nem API de voz. A geração pode demorar, principalmente em respostas longas. Compare com o Piper abaixo; a voz salva só muda ao Salvar configurações.';
    document.getElementById('setting-tts_voice').parentElement.style.display=document.getElementById('setting-tts_provider').value==='edge'?'':'none';
    const fish=document.getElementById('fish-voice-status');
    fish.hidden=document.getElementById('setting-tts_provider').value!=='fish-audio';
    if(!fish.hidden){
      const voice=this.settings?.fish_voice;
      fish.textContent=(voice?.title||'Jarvis (UCM) - Português Brasileiro')+' · '+
        (voice?.configured?'Chave configurada. O texto das respostas será enviado à Fish Audio.':'Falta a chave Fish Audio. Crie em fish.audio/app/api-keys, preencha FISH_API_KEY no .env e reinicie o JARVIS.');
    }
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
  async loadBrowser() {
    const info=await this.api('browser');
    const select=document.getElementById('browser-profile');select.replaceChildren();
    for(const profile of info.profiles){const option=document.createElement('option');option.value=profile.directory;option.textContent=`${profile.name} · ${profile.directory}`;select.appendChild(option);}
    select.value=info.profile;document.getElementById('browser-mode').value=info.mode;
    document.getElementById('browser-status').textContent=info.connected?`Chrome conectado · ${info.connected_profile||info.profile}`:
      info.mode==='isolated'?'Perfil separado selecionado explicitamente; entre manualmente no YouTube.':
      info.authorization_available?'Chrome pronto para solicitar autorização. Clique em Conectar.':'Autorize no Chrome para usar sua sessão existente. Nenhum perfil separado será aberto automaticamente.';
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
  showReminderAlert(item) {
    this.reminderAlert=item.id;
    document.getElementById('reminder-alert-text').textContent=`Senhor, ${item.kind==='alarm'?'alarme':'lembrete'}: ${item.text}`;
    document.getElementById('reminder-alert').hidden=false;
  }
  async showReminders() {
    const {reminders}=await this.api('reminders');
    const box=document.getElementById('reminder-list');box.replaceChildren();
    for(const item of reminders){
      const row=document.createElement('p');
      const text=document.createElement('span');text.textContent=`${new Date(item.due).toLocaleString('pt-BR')} · ${item.text} · ${item.state==='due'?'VENCIDO':'AGENDADO'} `;
      const button=document.createElement('button');button.textContent='Encerrar';
      button.onclick=()=>this.safe(async()=>{await this.api('reminders/'+item.id+'/dismiss',{});await this.showReminders();await this.reconcile();});
      row.append(text,button);box.append(row);
    }
    if(!reminders.length)box.textContent='Nenhum aviso pendente.';
  }
  bind() {
    const on=(id,fn)=>document.getElementById(id).addEventListener('click',()=>this.safe(fn));
    document.getElementById('command-form').onsubmit=e=>{e.preventDefault();const input=document.getElementById('cmd-input');const text=input.value;this.safe(async()=>{await this.sendCommand(text);input.value='';});};
    on('mic-trigger-btn',async()=>{if(this.state==='LISTENING'){this.send({action:'microphone_off'});this.voiceRequest=null;this.setState('IDLE');}else this.startListening();});
    document.getElementById('continuous-mic-cb').onchange=e=>{this.continuousMode=e.target.checked;this.safe(async()=>{if(this.continuousMode)this.startListening(true);else {this.send({action:'microphone_off'});this.voiceRequest=null;}});};
    on('cancel-task-btn',async()=>{await this.api('audio/stop',{});if(this.activeTask)await this.api('tasks/'+this.activeTask+'/cancel',{});this.setState('CANCELLED');});
    on('mute-btn',async()=>{await this.api('audio/stop',{});this.continuousMode=false;document.getElementById('continuous-mic-cb').checked=false;this.setState('IDLE');});
    on('autostart-btn',async()=>{const r=await this.api('autostart/toggle',{});this.setAutostartStatus(r.enabled);this.addFeedEntry('SISTEMA',r.message);});
    on('stop-jarvis-btn',async()=>{this.stopping=true;await this.api('shutdown',{});this.setState('CANCELLED');});
    on('clear-log-btn',async()=>this.feed.replaceChildren());
    on('history-btn',async()=>this.refreshHistory());
    on('browser-save',async()=>{await this.api('browser/settings',{mode:document.getElementById('browser-mode').value,profile:document.getElementById('browser-profile').value});await this.loadBrowser();});
    on('browser-authorize',async()=>{const result=await this.api('browser/authorize',{});document.getElementById('browser-status').textContent=result.message;});
    on('browser-connect',async()=>{document.getElementById('browser-status').textContent='Conectando ao seu Chrome…';const result=await this.api('browser/connect',{});document.getElementById('browser-status').textContent=result.message;await this.loadBrowser();});

    on('new-session-btn',async()=>{this.session=crypto.randomUUID();this.activeTask=null;this.contentTask=null;this.observedRevision=null;this.clearContent();this.showMedia({state:'unavailable',observed:true});this.text('recognized-request','Seu próximo pedido aparecerá aqui.');localStorage.setItem('jarvis-session',this.session);await this.refreshHistory();});
    on('control-panel-btn',async()=>{document.getElementById('control-panel').showModal();await this.loadSettings();});
    on('close-panel',async()=>document.getElementById('control-panel').close());
    on('reminders-refresh',async()=>this.showReminders());
    on('reminder-alert-dismiss',async()=>{if(this.reminderAlert)await this.api('reminders/'+this.reminderAlert+'/dismiss',{});document.getElementById('reminder-alert').hidden=true;await this.reconcile();});
    on('save-settings',async()=>{
      const data={};for(const key of ['provider','model','fallback_provider','fallback_model','tts_provider','tts_voice','stt_provider','input_device'])data[key]=document.getElementById('setting-'+key).value;
      data.speech_enabled=document.getElementById('setting-speech_enabled').checked;
      if(document.getElementById('setting-voice_busy_policy'))data.voice_busy_policy=document.getElementById('setting-voice_busy_policy').value;
      data.piper_profile=document.getElementById('setting-piper_profile').value;
      await this.api('settings',data);await this.loadSettings();document.getElementById('panel-message').textContent='Configurações salvas e verificadas.';
    });
    on('discover-models',async()=>{await Promise.all([this.loadModels(),this.loadModels(true)]);});
    on('voice-preview',async()=>{
      const [provider,profile]=document.getElementById('voice-preview-option').value.split(':');
      const task=await this.api('voice/preview',{session:this.session,provider,profile,sample:document.getElementById('voice-sample').value});
      this.activeTask=task.id;this.previewTask=task.id;this.finishedTasks.delete(task.id);
      document.getElementById('voice-preview-stop').disabled=false;
      this.text('voice-preview-status','Comparação recebida. Acompanhe fila, geração e reprodução no painel.');
    });
    on('voice-preview-stop',async()=>{if(this.previewTask)await this.api('tasks/'+this.previewTask+'/cancel',{});});
    document.getElementById('setting-tts_provider').onchange=()=>this.updateVoiceFields();
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
