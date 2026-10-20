"""Local HUD/API. A browser session cookie plus Host/Origin checks protect tools."""
import asyncio
from contextlib import asynccontextmanager,suppress
import json
import re
import secrets
from fastapi import FastAPI,Request,WebSocket,WebSocketDisconnect
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from core.config import config,settings,provider_key
from core.safety import atomic_write,redact
from core.assistant_service import AssistantService
from core.hermes_runtime import list_models
from core.memory_obsidian import obsidian_memory
from core.audio_manager import audio_manager
from core.system_monitor import system_monitor
from core.autostart import autostart_service
from core.reminders import reminders
from core.local_model import local_model, MODEL as LOCAL_MODEL

COOKIE = secrets.token_urlsafe(32)
connections = set()
send_lock = asyncio.Lock()
shutdown_callback = None
voice_runner = None
voice_continuous = False
voice_epoch = 0
voice_requests = set()

async def warm_transcription():
    try:
        await asyncio.to_thread(audio_manager.prepare_local_transcriber)
    except Exception as exc:
        await broadcast({'type':'notice','text':'Transcrição local indisponível: '+redact(str(exc))[:300]})

async def warm_voice():
    try:
        if settings()['tts_provider']=='qwen-local':
            from core.qwen_voice import qwen_voice
            await asyncio.to_thread(qwen_voice.prepare,audio_manager._cancel)
        else:
            from core.neural_voice import neural_voice
            await asyncio.to_thread(neural_voice.warmup)
    except Exception as exc:
        await broadcast({'type':'notice','text':'Voz neural local indisponível: '+redact(str(exc))[:300]})

async def broadcast(message):
    encoded = json.dumps(message,ensure_ascii=False)
    async with send_lock:
        for ws in list(connections):
            try:
                await asyncio.wait_for(ws.send_text(encoded),2)
            except Exception:
                connections.discard(ws)

assistant = AssistantService(broadcast)

def valid_id(value):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',value):
        raise ValueError('Identificador inválido.')
    return value

def trusted(host,origin):
    if host not in (f'127.0.0.1:{config.PORT}',f'localhost:{config.PORT}','testserver'):
        return False
    return not origin or origin in (f'http://{host}',f'https://{host}')

async def telemetry():
    while True:
        if connections:
            metrics = await asyncio.to_thread(system_monitor.get_metrics)
            metrics['autostart_enabled'] = autostart_service.is_enabled()
            await broadcast({'type':'telemetry','data':metrics})
        await asyncio.sleep(2)

async def reminder_loop():
    import time
    sounded={}
    while True:
        due=await asyncio.to_thread(reminders.tick)
        for item in due:
            elapsed=time.monotonic()-sounded.get(item['id'],float('-inf'))
            if elapsed>=(15 if item['kind']=='alarm' else 60):
                sounded[item['id']]=time.monotonic()
                await broadcast({'type':'reminder_due','reminder':item})
                def sound():
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                try:
                    await asyncio.to_thread(sound)
                except Exception:
                    await broadcast({'type':'notice','text':'O aviso está no painel, mas o som do Windows não pôde ser reproduzido.'})
        active={item['id'] for item in due}
        sounded={key:value for key,value in sounded.items() if key in active}
        await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app):
    assistant.store.recover()
    loop = asyncio.get_running_loop()
    def state(value):
        loop.call_soon_threadsafe(lambda:asyncio.create_task(broadcast({'type':'state','state':value})))
    def level(value):
        loop.call_soon_threadsafe(lambda:asyncio.create_task(broadcast({'type':'audio_level','level':value})))
    audio_manager.on_state_change = state
    audio_manager.on_audio_level = level
    periodic = asyncio.create_task(telemetry())
    reminder_task=asyncio.create_task(reminder_loop())
    warmup=asyncio.create_task(warm_transcription()) if settings()['stt_provider']=='whisper-local' else None
    voice_warmup=asyncio.create_task(warm_voice()) if settings()['tts_provider'] in ('piper','qwen-local') else None
    try:
        yield
    finally:
        audio_manager.stop()
        if voice_runner:
            voice_runner.cancel()
            await asyncio.gather(voice_runner,return_exceptions=True)
        periodic.cancel()
        reminder_task.cancel()
        await asyncio.gather(reminder_task,return_exceptions=True)
        with suppress(asyncio.CancelledError):
            await periodic
        await assistant.close()
        if warmup:
            warmup.cancel()
            await asyncio.gather(warmup,return_exceptions=True)
        if voice_warmup:
            voice_warmup.cancel()
            await asyncio.gather(voice_warmup,return_exceptions=True)
        audio_manager.on_state_change = None
        audio_manager.on_audio_level = None

app = FastAPI(title='JARVIS / Hermes',version='4.0',lifespan=lifespan)

@app.middleware('http')
async def local_access(request:Request,call_next):
    if not trusted(request.headers.get('host',''),request.headers.get('origin')):
        return JSONResponse({'detail':'Origem não autorizada.'},status_code=403)
    if request.url.path.startswith('/api/') and not secrets.compare_digest(request.cookies.get('jarvis_session',''),COOKIE):
        return JSONResponse({'detail':'Abra a interface local primeiro.'},status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else 'no-cache'
    if request.url.path=='/':
        response.set_cookie('jarvis_session',COOKIE,httponly=True,samesite='strict')
    return response

@app.exception_handler(ValueError)
async def value_error(request,exc):
    return JSONResponse({'detail':redact(str(exc))},status_code=400)

@app.exception_handler(KeyError)
async def missing(request,exc):
    return JSONResponse({'detail':'Registro não encontrado.'},status_code=404)

@app.exception_handler(RuntimeError)
async def unavailable(request,exc):
    return JSONResponse({'detail':redact(str(exc))},status_code=503)

@app.exception_handler(PermissionError)
async def denied(request,exc):
    return JSONResponse({'detail':redact(str(exc))},status_code=403)

@app.exception_handler(FileNotFoundError)
async def file_missing(request,exc):
    return JSONResponse({'detail':'Arquivo não encontrado no diretório autorizado.'},status_code=404)

@app.exception_handler(TimeoutError)
async def timed_out(request,exc):
    return JSONResponse({'detail':'O limite de tempo foi atingido. Confira a tarefa e os checkpoints.'},status_code=504)

class CommandRequest(BaseModel):
    command:str = Field(min_length=1,max_length=12000)
    session:str = 'default'
    id:str|None = None

class MemoryRequest(BaseModel):
    action:str
    target:str = 'user'
    content:str = Field(default='',max_length=2200)
    old_text:str = Field(default='',max_length=2200)
    source:str = 'user_statement'

class NoteRequest(BaseModel):
    path:str
    content:str = Field(max_length=100000)
    expected_hash:str|None = None
    source:str = 'user_statement'

class LocalActionRequest(BaseModel):
    action:str
    session:str='default'
    id:str

@app.post('/api/actions')
async def local_action(req:LocalActionRequest):
    """Exact UI shortcuts use deterministic tools and no model calls."""
    from core.jarvis_tools import ToolService
    actions={
        'status':{'action':'system_status'},
        'vault':{'action':'open_target','path':'cofre'},
        'browser':{'action':'browser_open','query':'google'},
        'music':{'action':'play_music','query':'música'},
        'screenshot':{'action':'screenshot'},
    }
    if req.action.startswith('macro:'):
        actions[req.action]={'action':'macro_run','query':req.action.removeprefix('macro:')}
    if req.action not in actions:raise ValueError('Ação local desconhecida.')
    valid_id(req.id);valid_id(req.session)
    prompt='[Atalho local] '+req.action
    fresh=assistant.store.create(req.id,req.session,prompt)
    if not fresh:return assistant.store.get(req.id)
    async with assistant.lock:
        assistant.store.update(req.id,'running')
        await broadcast({'type':'state','state':'EXECUTING'})
        result=await asyncio.to_thread(ToolService(req.id).execute,actions[req.action])
        ok=not result.get('error') and result.get('verified') is not False and not result.get('needs_manual_verification')
        display=result.get('message') or json.dumps(result,ensure_ascii=False,indent=2)
        assistant.store.update(req.id,'completed' if ok else 'failed',result=display,error=result.get('error'),usage={'provider':'deterministic','api_calls':0,'input_tokens':0,'output_tokens':0,'estimated_usd':0})
        await broadcast({'type':'jarvis_response','response':display,'session':req.session})
        await broadcast({'type':'state','state':'COMPLETED' if ok else 'FAILED'})
    return assistant.store.get(req.id)

@app.get('/health')
async def health():
    return {'status':'online','engine':'Hermes AIAgent','configured_model':bool(settings()['model'])}

@app.post('/api/command',status_code=202)
async def command(req:CommandRequest):
    valid_id(req.session)
    if req.id:
        valid_id(req.id)
    return await assistant.submit(req.command,req.session,req.id)

@app.get('/api/tasks')
async def tasks(session:str|None=None):
    return {'tasks':assistant.store.list(session)}

@app.get('/api/tasks/{task_id}')
async def task(task_id:str):
    return assistant.store.get(task_id)

@app.post('/api/tasks/{task_id}/cancel')
async def cancel(task_id:str):
    return await assistant.cancel(task_id)

@app.post('/api/tasks/{task_id}/resume')
async def resume(task_id:str):
    return await assistant.resume(task_id)

@app.get('/api/history')
async def history(session:str='default'):
    valid_id(session)
    tasks=assistant.store.list(session)
    if tasks or settings()['provider']=='local-cpu':
        messages=[]
        for task in reversed(tasks):
            preview=task.get('usage',{}).get('provider')=='voice-preview'
            messages.append({'role':'user','content':'[Comparação de voz local]' if preview else task['prompt']})
            if task.get('result'): messages.append({'role':'assistant','content':('[Prévia de voz] ' if preview else '')+task['result']})
            elif task.get('error'): messages.append({'role':'assistant','content':task['error']})
        return {'messages':messages}
    return await assistant.runtime.run({'operation':'history','session':session},timeout=30)

@app.get('/api/settings')
async def get_settings():
    s = settings()
    from core.fish_voice import voice_status
    from core.qwen_voice import qwen_voice
    return {**s,'credentials':{p:bool(provider_key(p)) for p in ('openai-api','gemini','fish-audio')},
        'fish_voice':voice_status(),
        'qwen_voice':qwen_voice.status(),'local_model':local_model.status(),
        'vault':str(obsidian_memory.vault_dir),'workspace_roots':[str(p) for p in config.WORKSPACE_ROOTS],
        'limits':{'steps':config.MAX_STEPS,'output_tokens_per_call':config.MAX_OUTPUT_TOKENS,'task_tokens_soft':config.MAX_TASK_TOKENS,'context_chars':config.MAX_CONTEXT_CHARS,
                  'task_seconds':config.TASK_TIMEOUT,'daily_tasks':config.MAX_DAILY_TASKS,'daily_tokens_soft':config.MAX_DAILY_TOKENS}}

@app.post('/api/settings')
async def save_settings(changes:dict):
    current = settings()
    if set(changes)-set(current):
        raise ValueError('Configuração desconhecida. Credenciais e permissões só podem ser alteradas no backend.')
    candidate = {**current,**changes}
    if candidate['provider'] not in ('openai-api','gemini','local-cpu') or candidate['fallback_provider'] not in ('','openai-api','gemini'):
        raise ValueError('Provedor inválido.')
    if candidate['tts_provider'] not in ('offline','piper','qwen-local') or candidate['stt_provider'] not in ('google-web','whisper-local','openai'):
        raise ValueError('Provedor de áudio inválido.')
    for name in ('model','fallback_model','tts_voice'):
        if not isinstance(candidate[name],str) or len(candidate[name])>120 or not re.fullmatch(r'[a-zA-Z0-9_./:-]*',candidate[name]):
            raise ValueError('Identificador de modelo/voz inválido.')
    if not isinstance(candidate['speech_enabled'],bool):
        raise ValueError('speech_enabled deve ser booleano.')
    if candidate['voice_busy_policy'] not in ('wait','interrupt'):
        raise ValueError('Política de voz inválida: wait ou interrupt.')
    if candidate['piper_profile'] not in ('original','natural'):raise ValueError('Perfil Piper inválido.')
    if not isinstance(candidate['input_device'],str) or len(candidate['input_device'])>300:
        raise ValueError('Microfone inválido.')
    if 'input_device' in changes and changes['input_device']:
        from core.audio_devices import resolve_input
        resolve_input(changes['input_device'])
    for name in ('input_price_per_million','output_price_per_million'):
        val = candidate[name]
        if val is not None and (not isinstance(val,(int,float)) or not 0<=val<=10000):
            raise ValueError('Preço inválido.')
    atomic_write(config.DATA_DIR/'settings.json',json.dumps(candidate,ensure_ascii=False,indent=2))
    return await get_settings()

@app.get('/api/browser')
async def browser_status():
    from core.chrome_session import connection_status
    from core.browser_control import browser_control
    status=await asyncio.to_thread(connection_status)
    return {**status,'connected':bool(browser_control.context),'connected_profile':browser_control.connected_profile}

@app.post('/api/voice/preview')
async def preview_voice(body:dict):
    provider=body.get('provider','qwen-local');profile=body.get('profile','original')
    if provider not in ('qwen-local','piper') or profile not in ('original','natural'):
        raise ValueError('Escolha uma voz local e um perfil válido.')
    cases=json.loads((config.BASE_DIR/'evaluations/voice_feedback.json').read_text(encoding='utf-8'))
    case=next((row for row in cases if row['id']==body.get('sample')),None)
    if not case:raise ValueError('Frase de comparação inválida.')
    return await assistant.preview_voice(valid_id(body.get('session','')),case['text'],provider,profile)

@app.get('/api/media/status')
async def observed_media(session:str):
    valid_id(session)
    from core.browser_control import browser_control
    from core.operational_context import context_for
    if assistant.lock.locked():return {'state':'refreshing','observed':False}
    return await asyncio.to_thread(browser_control.observe_media,context_for(session).media_tab_id)


@app.post('/api/browser/settings')
async def browser_settings_update(changes:dict):
    from core.chrome_session import save_browser_settings,browser_settings
    from core.browser_control import browser_control
    if assistant.lock.locked():raise ValueError('Aguarde a tarefa atual antes de trocar a conexão do navegador.')
    async with assistant.lock:
        previous=browser_settings()
        value=await asyncio.to_thread(save_browser_settings,changes)
        if value!=previous:
            await asyncio.to_thread(browser_control.close)
            browser_control.mode=value['mode']
    return await browser_status()


@app.post('/api/browser/authorize')
async def browser_authorize():
    from core.chrome_session import open_authorization
    return await asyncio.to_thread(open_authorization)


@app.post('/api/browser/connect')
async def browser_connect():
    from core.browser_control import browser_control
    from core.operational_context import context_for
    if assistant.lock.locked():raise ValueError('Aguarde a tarefa atual antes de conectar.')
    async with assistant.lock:
        return await asyncio.to_thread(browser_control.tool,{'action':'browser_connect'},context_for('browser-setup'))


@app.get('/api/audio/devices')
async def audio_devices():
    from core.audio_devices import input_devices,resolve_input
    devices=await asyncio.to_thread(input_devices)
    try:selected=resolve_input(settings()['input_device'])['id']
    except ValueError:selected=None
    from core.neural_voice import neural_voice
    return {'inputs':devices,'selected':selected,'last_capture':audio_manager.last_capture,
            'microphone_busy':audio_manager._mic_lock.locked(),'speech_busy':audio_manager.is_speaking,
            'task_busy':assistant.lock.locked(),
            'transcriber_ready':audio_manager._whisper is not None,'neural_voice_ready':neural_voice.ready}

@app.get('/api/models')
async def models(provider:str):
    if provider=='local-cpu':
        return {'provider':provider,'models':[LOCAL_MODEL] if local_model.prepared() else []}
    if provider not in ('openai-api','gemini'):
        raise ValueError('Provedor inválido.')
    return {'provider':provider,'models':await list_models(provider)}

@app.get('/api/reminders')
async def reminder_list():
    return {'reminders':await asyncio.to_thread(reminders.list)}

@app.post('/api/reminders/{identifier}/dismiss')
async def reminder_dismiss(identifier:str):
    return await asyncio.to_thread(reminders.dismiss,identifier)

@app.get('/api/usage')
async def usage():
    return {'observed':assistant.store.daily_usage(),'note':'Tokens reportados pelo provedor; estimativas dependem dos preços e data configurados. Limite de tokens diário é verificado na admissão; uma tarefa em curso pode ultrapassá-lo.'}

@app.get('/api/memory')
async def memory():
    return await assistant.runtime.run({'operation':'memory','args':{'action':'memory_list'}},timeout=30)

@app.get('/api/memory/events')
async def memory_events():
    path=config.DATA_DIR/'memory-events.json'
    return {'events':json.loads(path.read_text(encoding='utf-8')) if path.exists() else []}

@app.post('/api/memory')
async def update_memory(req:MemoryRequest):
    if req.action not in ('memory_add','memory_patch','memory_remove'):
        raise ValueError('Ação de memória inválida.')
    return await assistant.runtime.run({'operation':'memory','args':req.model_dump()},timeout=30)

@app.get('/api/vault/search')
async def vault_search(q:str=''):
    return {'sources':await asyncio.to_thread(obsidian_memory.search,q)}

@app.get('/api/vault/note')
async def vault_read(path:str):
    return await asyncio.to_thread(obsidian_memory.read,path)

@app.post('/api/vault/note')
async def vault_write(req:NoteRequest):
    return await asyncio.to_thread(obsidian_memory.write,req.path,req.content,req.expected_hash,req.source)

@app.get('/api/status')
async def status():
    data = await asyncio.to_thread(system_monitor.get_metrics)
    data['autostart_enabled'] = autostart_service.is_enabled()
    return data

@app.post('/api/autostart/toggle')
async def autostart():
    ok,message = await asyncio.to_thread(autostart_service.disable if autostart_service.is_enabled() else autostart_service.enable)
    return {'success':ok,'message':message,'enabled':autostart_service.is_enabled()}

@app.post('/api/audio/stop')
async def audio_stop():
    global voice_continuous,voice_epoch
    voice_continuous = False
    voice_epoch += 1
    audio_manager.stop()
    await broadcast({'type':'state','state':'EXECUTING' if assistant.lock.locked() else 'IDLE'})
    return {'status':'stopped'}

async def listen(session,continuous=False,request_id=None,epoch=None):
    global voice_continuous
    from core.command_text import normalize_command,is_vocative
    from core.voice_diagnostics import record_event
    voice_continuous = continuous
    epoch=voice_epoch if epoch is None else epoch
    request_id=request_id or secrets.token_hex(16)
    loop=asyncio.get_running_loop()
    def state(value):
        if epoch==voice_epoch:
            asyncio.run_coroutine_threadsafe(broadcast({'type':'state','state':value,'session':session,'voice_request_id':request_id}),loop).result(timeout=4)
    failed=False
    try:
        if assistant.lock.locked() or audio_manager.is_speaking:
            await broadcast({'type':'notice','session':session,'text':'Pedido de microfone recebido. Aguarde o indicador ESCUTANDO; Interromper continua disponível.'})
            if settings()['voice_busy_policy']=='interrupt':await assistant.interrupt_session(session,reason='listen_interrupt')
            await broadcast({'type':'state','state':'WAITING','session':session,'voice_request_id':request_id})
        while True:
            if epoch!=voice_epoch:break
            if (not continuous or not assistant.lock.locked()) and not audio_manager.is_speaking:
                from core.operational_context import context_for
                text = await asyncio.to_thread(audio_manager.listen_and_transcribe,on_state=state,vocabulary=context_for(session).recognition_hints())
                if epoch!=voice_epoch:break
                await broadcast({'type':'audio_diagnostics','data':audio_manager.last_capture,'session':session})
                if text:
                    normalized=normalize_command(text)
                    trace={'source':'voice','original_transcription':text,'normalized_text':normalized,'capture':dict(audio_manager.last_capture)}
                    record_event('transcribed',request_id=request_id,**trace)
                    await broadcast({'type':'transcription','session':session,'original':text,'normalized':normalized,'final':True,'voice_request_id':request_id})
                    if re.fullmatch(r'(?:interrompa|interromper|cancele a tarefa|cancelar a tarefa)[ .?!]*',normalized,re.I):
                        await assistant.interrupt_session(session)
                    elif not continuous or any(is_vocative(word) or word.casefold() in ('javis','jervis') for word in re.findall(r'\w+',text)[:5]):
                        task=await assistant.submit(text,session,request_id if not continuous else None,input_data=trace)
                        record_event('submitted',request_id=request_id,task_id=task['id'])
                    else:
                        await broadcast({'type':'notice','session':session,'text':'Fala detectada, mas sem o vocativo do modo contínuo. Diga “Jarvis” antes do pedido ou use o botão de fala única.'})
                elif not continuous:
                    captured=audio_manager.last_capture
                    name=captured.get('device','selecionado')
                    message=(f'Nenhuma fala detectada no microfone {name}. Confira o mute do headset e a seleção em Configurações.'
                             if not captured.get('speech_detected') else 'Áudio capturado, mas a transcrição não reconheceu palavras. Tente uma frase curta e clara.')
                    if captured.get('reason')!='cancelled':
                        await broadcast({'type':'notice','text':message,'session':session})
                        if hasattr(assistant,'acknowledge'):await assistant.acknowledge(session,message,outcome='failed')
                if not continuous or not voice_continuous:break
            elif continuous and not voice_continuous:break
            await asyncio.sleep(.5)
    except Exception as exc:
        failed=True
        await broadcast({'type':'notice','text':'Microfone/transcrição indisponível: '+redact(str(exc))[:400],'session':session})
        if epoch==voice_epoch and hasattr(assistant,'acknowledge'):
            await assistant.acknowledge(session,'Senhor, não consegui concluir a captura ou transcrição. Confira o microfone no painel.',outcome='failed')
        if epoch==voice_epoch:await broadcast({'type':'state','state':'FAILED','session':session,'voice_request_id':request_id})
    finally:
        await broadcast({'type':'voice_finished','session':session,'voice_request_id':request_id})
        if epoch==voice_epoch and not failed and not assistant.lock.locked() and not assistant.runners:
            await broadcast({'type':'state','state':'IDLE','session':session,'voice_request_id':request_id})

@app.post('/api/shutdown')
async def shutdown():
    await assistant.close()
    audio_manager.stop()
    if shutdown_callback:
        shutdown_callback()
    return {'status':'shutting_down' if shutdown_callback else 'tasks_stopped'}

@app.websocket('/ws')
async def websocket(ws:WebSocket):
    global voice_runner,voice_continuous,voice_epoch
    if not trusted(ws.headers.get('host',''),ws.headers.get('origin')) or not secrets.compare_digest(ws.cookies.get('jarvis_session',''),COOKIE):
        await ws.close(code=1008)
        return
    await ws.accept()
    connections.add(ws)
    await ws.send_json({'type':'init','telemetry':system_monitor.get_metrics()})
    try:
        while True:
            raw = await ws.receive_text()
            if len(raw)>16000:
                raise ValueError('Mensagem muito grande.')
            try:
                msg = json.loads(raw)
                action = msg.get('action')
                if action=='command':
                    session = valid_id(msg.get('session','default'))
                    task_id = valid_id(msg['id']) if msg.get('id') else None
                    task = await assistant.submit(msg.get('command',''),session,task_id)
                    await ws.send_json({'type':'task_updated','task':task})
                elif action=='listen_trigger':
                    request_id=valid_id(msg.get('id') or secrets.token_hex(16))
                    if request_id in voice_requests:
                        await ws.send_json({'type':'notice','text':'Este pedido de microfone já foi recebido.'})
                        continue
                    if not voice_runner or voice_runner.done():
                        if len(voice_requests)>=100:voice_requests.clear()
                        voice_requests.add(request_id)
                        voice_epoch+=1
                        voice_runner = asyncio.create_task(listen(valid_id(msg.get('session','default')),bool(msg.get('continuous')),request_id,voice_epoch))
                    else:await ws.send_json({'type':'notice','text':'O microfone já está capturando ou processando uma fala; aguarde ou use Interromper.'})
                elif action=='microphone_off':
                    voice_continuous = False
                    voice_epoch+=1
                    audio_manager.stop()
                elif action=='cancel':
                    if msg.get('id'):
                        await assistant.cancel(msg['id'])
                    else:
                        audio_manager.stop()
                elif action=='toggle_autostart':
                    result = await autostart()
                    await ws.send_json({'type':'autostart_status',**result})
                elif action=='shutdown':
                    await shutdown()
            except (ValueError,KeyError) as exc:
                await ws.send_json({'type':'notice','text':redact(str(exc))})
    except (WebSocketDisconnect,RuntimeError):
        pass
    finally:
        connections.discard(ws)

app.mount('/static',StaticFiles(directory=str(config.WEB_DIR)),name='static')

@app.get('/')
async def index():
    return FileResponse(config.WEB_DIR/'index.html')
