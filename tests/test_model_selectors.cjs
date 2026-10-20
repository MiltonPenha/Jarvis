// Catalog behavior tests; no browser, cloud generation, or third-party packages.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

function setup(globals={}){
  const elements=new Map();
  const element=()=>({value:'',textContent:'',disabled:false,hidden:false,parentElement:{style:{}},children:[],
    classList:{values:new Set(),contains(value){return this.values.has(value);},add(value){this.values.add(value);},remove(value){this.values.delete(value);},toggle(value,on){if(on??!this.values.has(value))this.values.add(value);else this.values.delete(value);}},
    replaceChildren(){this.children=[];this.value='';},append(child){this.children.push(child);}});
  const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},createElement:element};
  const context=vm.createContext({ReactorVisuals:class{},document,window:{addEventListener(){}},encodeURIComponent,Set,Promise,AbortSignal,...globals});
  const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
  vm.runInContext(source+'\nglobalThis.HUD=JarvisHUD;',context);
  const hud=Object.create(context.HUD.prototype);hud.modelRequests={};
  return {hud,get:id=>document.getElementById(id)};
}

test('an old task state cannot replace the newer active task',()=>{
  const {hud}=setup();hud.session='s';hud.activeTask='new';hud.finishedTasks=new Set();
  const states=[];hud.setState=value=>states.push(value);
  hud.message({type:'state',session:'s',task_id:'old',state:'FAILED'});
  hud.message({type:'state',session:'s',task_id:'new',state:'PROCESSING'});
  assert.deepEqual(states,['PROCESSING']);
});

test('old microphone results cannot reset a new capture',()=>{
  const {hud}=setup();hud.session='s';hud.voiceRequest='new';
  hud.message({type:'voice_finished',session:'s',voice_request_id:'old'});
  assert.equal(hud.voiceRequest,'new');
  hud.message({type:'voice_finished',session:'s',voice_request_id:'new'});
  assert.equal(hud.voiceRequest,null);
});

test('discovered models become visible choices without selecting one automatically',async()=>{
  const {hud,get}=setup();get('setting-provider').value='gemini';
  hud.api=async()=>({models:['gemini-flash','gemini-pro']});
  await hud.loadModels();
  assert.deepEqual(get('setting-model').children.map(o=>o.value),['','gemini-flash','gemini-pro']);
  assert.equal(get('setting-model').value,'');
  assert.match(get('models-status').textContent,/2 modelos/);
  assert.equal(get('setting-model').disabled,false);
});

test('fallback loads its own provider and disabling it does not query the catalog',async()=>{
  const {hud,get}=setup();get('setting-provider').value='gemini';get('setting-fallback_provider').value='openai-api';
  const calls=[];hud.api=async url=>{calls.push(url);return {models:url.includes('gemini')?['gemini-flash']:['gpt-fixture']};};
  await Promise.all([hud.loadModels(),hud.loadModels(true)]);
  assert.equal(get('setting-fallback_model').children[1].value,'gpt-fixture');
  get('setting-fallback_provider').value='';await hud.loadModels(true);
  assert.equal(calls.length,2);assert.equal(get('setting-fallback_model').disabled,true);
  assert.equal(get('setting-fallback_model').value,'');
});

test('slow catalog response cannot replace choices after a provider change',async()=>{
  const {hud,get}=setup();let finishOld;
  hud.api=url=>url.includes('openai-api')?new Promise(resolve=>{finishOld=resolve;}):Promise.resolve({models:['gemini-flash']});
  get('setting-provider').value='openai-api';const first=hud.loadModels();
  get('setting-provider').value='gemini';hud.setModelOptions(false,[]);await hud.loadModels();
  finishOld({models:['gpt-stale']});await first;
  assert.deepEqual(get('setting-model').children.map(o=>o.value),['','gemini-flash']);
});

test('catalog failure stays visible and preserves a configured model',async()=>{
  const {hud,get}=setup();get('setting-provider').value='gemini';hud.setModelOptions(false,[],'saved-model');
  hud.api=async()=>{throw new Error('gemini: HTTP 403. Verifique a credencial.');};
  await hud.loadModels();
  assert.equal(get('setting-model').value,'saved-model');
  assert.match(get('models-status').textContent,/HTTP 403/);
  assert.equal(get('setting-model').disabled,false);
});

test('Fish voice shows key setup status and hides unrelated voice input',()=>{
  const {hud,get}=setup();get('setting-tts_provider').value='fish-audio';
  hud.settings={fish_voice:{title:'Jarvis (UCM) - Português Brasileiro',configured:false}};
  hud.updateVoiceFields();
  assert.equal(get('fish-voice-status').hidden,false);
  assert.match(get('fish-voice-status').textContent,/FISH_API_KEY/);
  assert.equal(get('setting-tts_voice').parentElement.style.display,'none');
  hud.settings.fish_voice.configured=true;hud.updateVoiceFields();
  assert.match(get('fish-voice-status').textContent,/Chave configurada/);
  get('setting-tts_provider').value='edge';hud.updateVoiceFields();
  assert.equal(get('fish-voice-status').hidden,true);
  assert.equal(get('setting-tts_voice').parentElement.style.display,'');
});

test('local Qwen voice shows CPU-only mode without Fish key instructions',()=>{
  const {hud,get}=setup();get('setting-tts_provider').value='qwen-local';
  hud.updateVoiceFields();
  assert.equal(get('qwen-voice-status').hidden,false);
  assert.match(get('qwen-voice-status').textContent,/sem GPU/);
  assert.equal(get('fish-voice-status').hidden,true);
  assert.equal(get('setting-tts_voice').parentElement.style.display,'none');
});

const reply=(status,data)=>({status,ok:status>=200&&status<300,json:async()=>data});
const expired=()=>reply(403,{detail:'Abra a interface local primeiro.'});

test('concurrent expired requests share renewal and execute each command once',async()=>{
  let valid=false,renewals=0,finishRenewal;const effects=[];const requests=[];
  const {hud}=setup({fetch:async(url,options)=>{
    requests.push({url,options});
    if(url==='/'){
      renewals++;await new Promise(resolve=>{finishRenewal=resolve;});valid=true;return reply(200,{});
    }
    if(!valid)return expired();
    const body=JSON.parse(options.body);effects.push(body.id);return reply(200,{id:body.id});
  }});
  const first=hud.api('command',{id:'one',command:'Pause'});
  const second=hud.api('command',{id:'two',command:'Continue'});
  await new Promise(setImmediate);assert.equal(renewals,1);
  finishRenewal();const results=await Promise.all([first,second]);
  assert.deepEqual(results.map(row=>row.id),['one','two']);
  assert.deepEqual(effects,['one','two']);
  assert.ok(requests.every(row=>row.options.credentials==='same-origin'));
});

test('other forbidden responses and uncertain failures never replay a command',async()=>{
  for(const result of [reply(403,{detail:'Origem não autorizada.'}),reply(503,{detail:'Falha após envio.'}),new Error('Resposta perdida')]){
    let calls=0;
    const {hud}=setup({fetch:async()=>{calls++;if(result instanceof Error)throw result;return result;}});
    await assert.rejects(hud.api('command',{id:'stable'}));assert.equal(calls,1);
  }
});

test('persistent session failure retries once and shows one warning until recovery',async()=>{
  const events=[];let requests=0,fail=true;
  const {hud}=setup({fetch:async url=>{
    if(url==='/')return reply(200,{});
    requests++;return fail?expired():reply(200,{});
  }});
  hud.addFeedEntry=(sender,text)=>events.push(text);
  await hud.safe(()=>hud.api('reminders'));
  await hud.safe(()=>hud.api('reminders'));
  assert.equal(requests,4);assert.equal(events.length,1);
  assert.doesNotMatch(events[0],/Abra a interface local primeiro/);
  fail=false;await hud.api('reminders');fail=true;
  await hud.safe(()=>hud.api('reminders'));assert.equal(events.length,2);
});

test('websocket reconnect renews the cookie before opening one socket',async()=>{
  const events=[];let finishRenewal;
  const {hud}=setup({fetch:async url=>{events.push(url);await new Promise(resolve=>{finishRenewal=resolve;});return reply(200,{});},
    location:{protocol:'http:',host:'127.0.0.1:8000'},WebSocket:class{constructor(url){events.push(url);}}});
  const first=hud.connect();const duplicate=hud.connect();
  await duplicate;assert.deepEqual(events,['/']);
  finishRenewal();await first;
  assert.deepEqual(events,['/','ws://127.0.0.1:8000/ws']);
});

test('slow background reconciliation does not overlap on the next poll',async()=>{
  const {hud}=setup();let calls=0,finish;
  hud.api=async path=>{calls++;if(path==='reminders'){await new Promise(resolve=>{finish=resolve;});return {reminders:[]};}return {tasks:[]};};
  const first=hud.reconcile();await hud.reconcile();assert.equal(calls,1);
  finish();await first;assert.equal(calls,3);assert.equal(hud.reconciling,false);
});

test('stale tool, voice and response events cannot overwrite a newer request',()=>{
  const {hud,get}=setup();hud.session='s';hud.activeTask='new';hud.finishedTasks=new Set();
  hud.addFeedEntry=()=>{throw Error('stale response rendered');};
  for(const type of ['tool','speech','progress','jarvis_response','user_command'])hud.message({type,session:'s',task_id:'old',data:{phase:'playing',message:'old'},presentation:{stage:'confirmed',title:'old'}});
  assert.equal(get('content-title').textContent,'');assert.equal(get('speech-phase').textContent,'');
});

test('speech and media updates preserve the request state and content',()=>{
  const {hud,get}=setup();hud.state='WAITING';
  hud.showContent({stage:'selected',title:'Happy',channel:'Observed artist'});
  hud.showSpeech({phase:'playing',audio_seconds:4});
  hud.showMedia({state:'paused',observed:true,exists:true,title:'Other ongoing song',volume:.47});
  assert.equal(hud.state,'WAITING');assert.equal(get('content-title').textContent,'Happy');
  assert.equal(get('speech-phase').textContent,'Falando');assert.match(get('media-title').textContent,/47%/);
});

test('partial and final transcriptions have distinct labels without feed spam',()=>{
  const {hud,get}=setup();hud.session='s';let entries=0;hud.addFeedEntry=()=>entries++;
  hud.message({type:'transcription',text:'Jarvis',final:false});
  assert.match(get('transcript-kind').textContent,/parcial/);
  hud.message({type:'transcription',original:'Jarvis, toque Happy',normalized:'toque Happy',final:true});
  assert.match(get('transcript-kind').textContent,/final/);assert.equal(entries,0);
  hud.message({type:'progress',data:{message:'Pesquisando'}});hud.message({type:'progress',data:{message:'Conferindo'}});
  assert.equal(get('activity').textContent,'Conferindo');assert.equal(entries,0);
});

test('telemetry refresh updates compact values without rebuilding expanded details',()=>{
  const {hud,get}=setup();get('system-details').open=true;get('quick-actions').open=true;
  hud.setAutostartStatus=()=>{};
  hud.updateTelemetry({cpu_percent:47.2,ram_percent:62.6,disk_percent:75,cpu_cores:16,cpu_ghz:3.7,ram_used_gb:20,ram_total_gb:32,disk_free_gb:100,disk_total_gb:400,uptime:'2h',hostname:'PC'});
  assert.equal(get('cpu-val').textContent,'47%');assert.equal(get('ram-val').textContent,'63%');
  assert.equal(get('disk-sub').textContent,'100 GB livres / 400 GB');
  assert.equal(get('system-details').open,true);assert.equal(get('quick-actions').open,true);
});

test('content opens once, respects manual collapse and clears for the next task',()=>{
  const {hud,get}=setup();hud.session='s';hud.addFeedEntry=()=>{};
  hud.message({type:'user_command',session:'s',task_id:'first',text:'Toque uma música'});
  hud.showContent({stage:'selected',title:'Título observado'});
  assert.equal(get('task-content').open,true);
  get('task-content').open=false;
  hud.showContent({stage:'confirmed',title:'Título observado'});
  assert.equal(get('task-content').open,false);
  hud.activeTask=null;
  hud.message({type:'user_command',session:'s',task_id:'second',text:'Qual é o tempo?'});
  assert.equal(get('task-content').open,false);assert.equal(get('task-content').classList.contains('has-content'),false);
  assert.equal(get('content-phase').textContent,'Sem conteúdo');
});

test('media list identity clears stale choices and late presentations cannot overwrite it',()=>{
  const {hud,get}=setup();hud.activeTask='new';
  const options=[{position:2,title:'TAUZ - MADARA',channel:'Tauz',video_id:'gbS7o0F8eNs'}];
  hud.showContent({request_id:'new',source_task_id:'earlier',result_set_id:'list-a',stage:'awaiting_choice',query:'rap uma dara',candidates:options,title:'Escolha'});
  assert.equal(get('content-options').children.length,1);assert.equal(get('content-options').children[0].value,2);
  assert.match(get('content-origin').textContent,/Pesquisa anterior/);
  const node=get('content-options').children[0];
  hud.showContent({request_id:'new',result_set_id:'list-a',stage:'selected',candidates:options,title:'TAUZ - MADARA'});
  assert.equal(get('content-options').children[0],node);
  hud.showContent({request_id:'old',result_set_id:'old-list',stage:'confirmed',title:'Wrong old video'});
  assert.equal(get('content-title').textContent,'TAUZ - MADARA');
  hud.showContent({request_id:'new',result_set_id:'list-b',stage:'searching',query:'Happy',candidates:[],title:'Busca em andamento'});
  assert.equal(get('content-options').children.length,0);assert.match(get('content-phase').textContent,/Atualizando/);
  assert.doesNotMatch(get('content-origin').textContent,/rap uma dara/);
});

test('completion of a superseded task cannot replace the current content after it finishes',()=>{
  const {hud,get}=setup();hud.session='s';hud.activeTask=null;hud.finishedTasks=new Set();
  hud.showContent({stage:'confirmed',title:'New selection'});
  hud.message({type:'task_updated',session:'s',task_id:'old',task:{id:'old',state:'cancelled',input:{superseded_by:'new',presentation:{stage:'unconfirmed',title:'Old selection'}}}});
  assert.equal(get('content-title').textContent,'New selection');
});
