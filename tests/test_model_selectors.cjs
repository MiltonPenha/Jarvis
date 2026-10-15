// Catalog behavior tests; no browser, cloud generation, or third-party packages.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

function setup(){
  const elements=new Map();
  const element=()=>({value:'',textContent:'',disabled:false,hidden:false,parentElement:{style:{}},children:[],
    replaceChildren(){this.children=[];this.value='';},append(child){this.children.push(child);}});
  const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},createElement:element};
  const context=vm.createContext({ReactorVisuals:class{},document,window:{addEventListener(){}},encodeURIComponent,Set,Promise});
  const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
  vm.runInContext(source+'\nglobalThis.HUD=JarvisHUD;',context);
  const hud=Object.create(context.HUD.prototype);hud.modelRequests={};
  return {hud,get:id=>document.getElementById(id)};
}

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
