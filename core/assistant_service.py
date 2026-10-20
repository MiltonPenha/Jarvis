"""Single serialized entry point for text/voice and durable Hermes tasks."""
import asyncio
import time
import uuid
from core.config import config,settings,provider_key
from core.hermes_runtime import HermesRuntime
from core.task_store import TaskStore
from core.safety import redact
from core.local_runtime import direct_plan
from core.operational_context import context_for
from core.command_text import normalize_command,music_request

class AssistantService:
    def __init__(self,broadcast):
        self.broadcast = broadcast
        self.store = TaskStore()
        self.runtime = HermesRuntime()
        from core.local_runtime import LocalRuntime
        self.local_runtime = LocalRuntime(self.store)
        self.lock = asyncio.Lock()
        self.runners = {}
        self.cancelled = set()
        self.finished=set()
        self.speaking_task=None

    async def submit(self,command,session,task_id=None,input_data=None):
        task_id = task_id or str(uuid.uuid4())
        command = redact(command.strip())
        if not command or len(command)>12000:
            raise ValueError('Pedido vazio ou maior que 12000 caracteres.')
        usage = self.store.daily_usage()
        # Existing IDs remain retrievable even when the budget was reached.
        try:
            existing = self.store.get(task_id)
            if existing['session']!=session or existing['prompt']!=command:
                raise ValueError('ID já associado a outro pedido.')
            return existing
        except KeyError:
            pass
        context=context_for(session)
        if not context.music_goal:context.music_goal=self.store.last_music_goal(session)
        if not context.pending_music_query and not context.media_query:
            context.pending_music_query=self.store.pending_music(session)
        from core.music_intent import requested,is_correction
        from core.music_followup import confirmation_reply,reference_request,reference_context
        contextual=reference_request(command,context)
        snapshot=reference_context(context) if contextual else None
        reply=confirmation_reply(command);pending=context.music_goal.get('confirmation',{})
        previous_reply=self.store.get(context.music_task)['input'].get('confirmation_reply',{}) if context.music_task in self.runners else {}
        duplicate_reply=bool(reply and pending and previous_reply.get('id')==pending.get('id') and previous_reply.get('response')==reply)
        correction=is_correction(command);musical=requested(command,context) or bool(reply and pending and not duplicate_reply)
        direct=await asyncio.to_thread(direct_plan,command,context=context)
        if direct is None and not musical and settings()['provider']!='local-cpu' and (usage['tasks']>=config.MAX_DAILY_TASKS or usage['tokens']>=config.MAX_DAILY_TOKENS):
            raise ValueError('Orçamento diário atingido. Ajuste os limites no backend.')
        if len(self.runners)>=5:
            raise ValueError('Fila cheia. Aguarde ou cancele uma tarefa.')
        self.store.create(task_id,session,command)
        self.store.input_trace(task_id,{'source':'text','original_transcription':command,'normalized_text':normalize_command(command),**(input_data or {})})
        if contextual:self.store.input_trace(task_id,{'reference_requested':True,'reference_context':snapshot})
        if reply and pending and not contextual:
            self.store.input_trace(task_id,{'confirmation_reply':{'id':pending['id'],'response':reply,'source_task_id':pending.get('source_task_id')}})
        elif pending and pending.get('state')!='superseded' and not contextual and not (direct and direct.get('steps') and all(step['action'].startswith('browser_') for step in direct['steps'])):
            context.music_goal={**context.music_goal,'confirmation':{**pending,'state':'superseded'}}
            self.store.input_trace(task_id,{'music_goal':context.music_goal})
        if musical:
            previous_goal=dict(context.music_goal)
            if context.music_task and previous_goal.get('task_id')!=context.music_task:previous_goal={}
            self.store.input_trace(task_id,{'music_revision':context.music_revision+1,
                **({'correction_context':{'music_goal':previous_goal,'music_source':context.music_source}} if correction else {})})
            previous=context.music_task
            context.music_revision+=1;context.music_task=task_id
            if not correction and not reply and not contextual:context.music_source=command
            if previous and previous in self.runners:
                self.store.input_trace(previous,{'superseded_by':task_id})
                await self.cancel(previous,reason='superseded')
        self.runners[task_id] = asyncio.create_task(self.execute(task_id))
        return self.store.get(task_id)

    async def event(self,task_id,event):
        if self.superseded(task_id) and event.get('type')!='task_updated':return
        from core.feedback import content_update
        presentation=content_update(event)
        if presentation:
            presentation['request_id']=task_id
            self.store.input_trace(task_id,{'presentation':presentation})
            event['presentation']=presentation
        if event.get('type')=='speech':self.store.input_trace(task_id,{'speech_progress':event['data']})
        event['task_id'] = task_id
        event['session'] = self.store.get(task_id)['session']
        await self.broadcast(event)

    async def acknowledge(self,session,message,outcome='completed'):
        identifier='voice-feedback-'+uuid.uuid4().hex
        self.store.create(identifier,session,message)
        self.store.input_trace(identifier,{'source':'voice_feedback'})
        async with self.lock:
            await self.finish(identifier,outcome,message,usage={'provider':'direct','api_calls':0,'input_tokens':0,'output_tokens':0})
        await self.event(identifier,{'type':'task_updated','task':self.store.get(identifier)})

    def superseded(self,task_id):return bool(self.store.get(task_id).get('input',{}).get('superseded_by'))

    async def _say(self,task_id,text,allow_cancelled=False,provider=None,profile=None):
        from core.audio_manager import audio_manager
        loop=asyncio.get_running_loop();playback_deadline=None;generation_deadline=time.monotonic()+config.SPEECH_TIMEOUT
        await self.event(task_id,{'type':'speech','data':{'phase':'queued'}})
        # A manually requested correction may still be recording. Never speak
        # over it or let the recognizer hear our acknowledgement.
        queue_deadline=time.monotonic()+config.VOICE_MAX_SECONDS+8
        while audio_manager._mic_lock.locked() or audio_manager._speech_lock.locked():
            if self.superseded(task_id) or task_id in self.cancelled and not allow_cancelled:return {'state':'cancelled','delivered':False}
            if time.monotonic()>queue_deadline:return {'state':'busy','delivered':False,'error':'A saída de voz permaneceu ocupada. A resposta está na tela.'}
            await asyncio.sleep(.05)
        def speech_state(state):
            nonlocal playback_deadline,generation_deadline
            if state=='SPEAKING':playback_deadline=time.monotonic()+audio_manager.last_speech.get('audio_seconds',0)+5
            elif state=='PROCESSING':generation_deadline=time.monotonic()+config.SPEECH_TIMEOUT
            if not self.superseded(task_id) and (allow_cancelled or task_id not in self.cancelled):
                asyncio.run_coroutine_threadsafe(self.event(task_id,{'type':'speech','data':dict(audio_manager.last_speech)}),loop).result(timeout=4)
                if state=='SPEAKING':asyncio.run_coroutine_threadsafe(self.event(task_id,{'type':'state','state':state}),loop).result(timeout=4)
        await self.event(task_id,{'type':'progress','data':{'stage':'speech_preparing','message':'Preparando a resposta falada.'}})
        started=time.monotonic();self.speaking_task=task_id
        options={**({'provider':provider} if provider else {}),**({'profile':profile} if profile else {})}
        speech=asyncio.create_task(asyncio.to_thread(audio_manager.speak,text,on_state=speech_state,
            cancelled=lambda:self.superseded(task_id) or task_id in self.cancelled and not allow_cancelled,**options))
        try:
            while not speech.done():
                if self.superseded(task_id) or task_id in self.cancelled and not allow_cancelled:
                    await asyncio.to_thread(audio_manager.stop)
                    try:await asyncio.wait_for(asyncio.shield(speech),5)
                    except TimeoutError:pass
                    return {'state':'cancelled','delivered':False}
                remaining=min(playback_deadline or generation_deadline,started+240)-time.monotonic()
                if remaining<=0:raise TimeoutError()
                await asyncio.wait({speech},timeout=min(.1,remaining))
            result=speech.result()
            return {**result,'delivered':result.get('state')=='completed' and not result.get('error'),'elapsed_seconds':round(time.monotonic()-started,3)}
        except TimeoutError:
            await asyncio.to_thread(audio_manager.stop)
            try:await asyncio.wait_for(asyncio.shield(speech),5)
            except TimeoutError:pass
            return {'state':'timeout','delivered':False,'error':'A voz excedeu o tempo limite e foi interrompida. A resposta está na tela.'}
        except asyncio.CancelledError:
            await asyncio.to_thread(audio_manager.stop);raise
        except Exception as exc:return {'state':'failed','delivered':False,'error':redact(str(exc))[:500] or type(exc).__name__}
        finally:self.speaking_task=None

    async def preview_voice(self,session,text,provider,profile):
        if any(self.store.get(identifier)['session']==session for identifier in self.runners):
            raise ValueError('Aguarde a solicitação atual terminar antes de comparar vozes.')
        if len(self.runners)>=5:raise ValueError('Fila cheia. Aguarde a saída de voz.')
        identifier='voice-preview-'+uuid.uuid4().hex
        self.store.create(identifier,session,'[Prévia de voz local] '+provider)
        self.store.input_trace(identifier,{'source':'voice_preview','voice_preview':{'provider':provider,'profile':profile}})
        async def run():
            try:
                async with self.lock:
                    if identifier in self.cancelled:await self.finish(identifier,'cancelled');return
                    await self.event(identifier,{'type':'user_command','text':'Comparação de voz local: '+provider,'source':'voice_preview'})
                    await self.event(identifier,{'type':'state','state':'EXECUTING'})
                    await self.finish(identifier,'completed','Prévia de voz ('+provider+'): '+text,spoken=text,usage={'provider':'voice-preview','api_calls':0})
            finally:
                self.runners.pop(identifier,None);self.cancelled.discard(identifier)
                await self.event(identifier,{'type':'task_updated','task':self.store.get(identifier)})
        self.runners[identifier]=asyncio.create_task(run())
        return self.store.get(identifier)

    async def finish(self,task_id,state,message='',usage=None,spoken=None,error=None,clarification=False):
        """One final visual/voice boundary for success, failure and clarification."""
        if task_id in self.finished:return
        self.finished.add(task_id);usage=usage or {}
        if self.superseded(task_id) or self.store.get(task_id)['input'].get('cancel_reason')=='listen_interrupt':
            self.store.input_trace(task_id,{'final_feedback':{'state':'suppressed','delivered':False,'reason':'superseded_or_listening'}})
            self.store.update(task_id,'cancelled',usage=usage);return
        if task_id in self.cancelled:state='cancelled'
        if state=='cancelled':message=spoken='Senhor, a solicitação foi cancelada.'
        if not message:message='Senhor, não consegui concluir a solicitação.'
        voice=spoken or message
        if not voice.lower().startswith('senhor'):voice='Senhor, '+voice
        from core.audio_manager import speech_text
        voice=speech_text(voice)
        outcome='clarification' if clarification and state=='completed' else state
        self.store.update(task_id,'running',result=message,usage=usage,error=error)
        self.store.input_trace(task_id,{'final_feedback':{'state':'pending','outcome':outcome,'text':voice,'delivered':False}})
        await self.event(task_id,{'type':'jarvis_response','response':message,'meta':{'usage':usage,'outcome':outcome}})
        delivered={'state':'disabled','delivered':False}
        preview=self.store.get(task_id)['input'].get('voice_preview')
        if settings()['speech_enabled'] or preview:
            delivered=await self._say(task_id,voice,allow_cancelled=state=='cancelled',**(preview or {}))
            if self.superseded(task_id):
                delivered={**delivered,'state':'suppressed','delivered':False,'reason':'superseded'};state='cancelled'
            elif task_id in self.cancelled and state!='cancelled':
                state='cancelled';message='Senhor, a solicitação foi cancelada.'
                await self.event(task_id,{'type':'notice','text':message})
                delivered=await self._say(task_id,message,allow_cancelled=True)
        usage['speech_seconds']=delivered.get('elapsed_seconds',0)
        self.store.input_trace(task_id,{'speech_result':delivered,'speech_seconds':usage['speech_seconds'],
            'final_feedback':{'state':delivered['state'],'outcome':outcome if state=='completed' else state,'delivered':delivered.get('delivered',False),'text':delivered.get('text',voice)}})
        await self.event(task_id,{'type':'speech','data':{'phase':delivered['state'],**delivered}})
        if delivered.get('error'):await self.event(task_id,{'type':'notice','text':'Falha na resposta falada: '+delivered['error']})
        self.store.update(task_id,state,result=message,usage=usage,error=error)
        await self.event(task_id,{'type':'state','state':'WAITING' if clarification and state=='completed' else {'completed':'COMPLETED','failed':'FAILED','cancelled':'CANCELLED'}[state]})

    async def execute(self,task_id):
        try:
            async with self.lock:
                if task_id in self.cancelled:
                    await self.finish(task_id,'cancelled');return
                task = self.store.get(task_id)
                s = settings()
                command=normalize_command(task['prompt'])
                direct=await asyncio.to_thread(direct_plan,command,context=context_for(task['session']))
                from core.music_intent import requested
                music_candidate=task.get('input',{}).get('reference_requested') or requested(task['prompt'],context_for(task['session']))
                if direct is None and music_candidate:
                    direct={'steps':[],'question':''}  # Music extraction always uses the CPU interpreter.
                self.store.input_trace(task_id,{'configured_provider':s['provider'],'configured_model':s['model'],
                    'execution_provider':'local-cpu' if music_candidate else 'direct' if direct is not None else s['provider']})
                if direct is None and s['provider']!='local-cpu' and self.store.daily_usage()['tokens']>=config.MAX_DAILY_TOKENS:
                    raise ValueError('Orçamento diário de tokens atingido antes de iniciar a tarefa da fila.')
                self.store.update(task_id,'running')
                await self.event(task_id,{'type':'state','state':'PROCESSING'})
                await self.event(task_id,{'type':'user_command','text':task['prompt'],'source':task['input'].get('source','text')})
                if direct is None and not s['model']:
                    raise ValueError('Escolha e salve um modelo na lista de Configurações. Se a lista não carregar, confira a chave no backend e use Atualizar modelos.')
                if direct is None and s['provider']!='local-cpu' and not provider_key(s['provider']):
                    raise ValueError('Credencial ausente. Configure OPENAI_API_KEY ou GEMINI_API_KEY no backend e reinicie.')
                started = time.monotonic()
                first_event = None
                async def progress(event):
                    nonlocal first_event
                    if self.superseded(task_id):return
                    if first_event is None:
                        first_event = time.monotonic()-started
                    if event['type']=='tool':
                        await self.event(task_id,{'type':'state','state':'EXECUTING'})
                    await self.event(task_id,event)
                request = {'id':task_id,'session':task['session'],'command':command,'original_command':task['prompt'],'settings':s}
                request['operational_context']=context_for(task['session']).compact()
                if direct is not None: request['direct_plan']=direct
                try:
                    engine=self.local_runtime if direct is not None or s['provider']=='local-cpu' else self.runtime
                    result = await engine.run(request,progress,timeout=config.TASK_TIMEOUT)
                except RuntimeError as exc:
                    # Provider failures before tool admission may use the explicit
                    # fallback. Configuration, cancellation and timeouts fail closed.
                    if direct is not None or s['provider']=='local-cpu' or not s.get('fallback_provider') or not s.get('fallback_model') or self.store.get(task_id)['tools'] or task_id in self.cancelled:
                        raise
                    result={'error':str(exc)}
                # A configured fallback can run only before any effect was admitted.
                # No full-turn replay is ever attempted after tool execution.
                prior_usage=None
                if direct is None and s['provider']!='local-cpu' and result.get('error') and not result.get('budget_exhausted') and s.get('fallback_provider') and s.get('fallback_model') and not self.store.get(task_id)['tools']:
                    prior_usage=result.get('usage',{})
                    remaining=config.TASK_TIMEOUT-(time.monotonic()-started)
                    if remaining<10:
                        raise TimeoutError('Orçamento total da tarefa esgotado antes do fallback.')
                    await self.event(task_id,{'type':'notice','text':'Fallback configurado: '+s['fallback_provider']+' / '+s['fallback_model']})
                    request['settings'] = {**s,'provider':s['fallback_provider'],'model':s['fallback_model']}
                    result = await self.runtime.run(request,progress,timeout=remaining)
                usage = result.get('usage',{})
                if prior_usage is not None:
                    usage['attempts']=[prior_usage,dict(usage)]
                    for key in ('input_tokens','output_tokens','cache_read_tokens','cache_write_tokens','api_calls'):
                        usage[key]=usage.get(key,0)+prior_usage.get(key,0)
                    usage['estimated_usd']=None
                    usage['pricing_note']='Fallback: configure preços por provedor antes de estimar o custo conjunto.'
                usage['first_event_seconds'] = first_event
                if result.get('cancelled') or task_id in self.cancelled:
                    await self.finish(task_id,'cancelled',usage=usage);return
                if result.get('error') or not result.get('response'):
                    self.store.update(task_id,'failed',usage=usage,error=result.get('error'))
                    raise RuntimeError(result.get('error') or 'Hermes não retornou resposta.')
                if result.get('effect_errors') or any(t['state']=='failed' for t in self.store.get(task_id)['tools']):
                    self.store.update(task_id,'failed',usage=usage,error='Uma ferramenta falhou; consulte os checkpoints.')
                    raise RuntimeError('A tarefa terminou com falha de ferramenta. Consulte os checkpoints; nenhum sucesso integral foi confirmado.')
                await self.finish(task_id,'completed',result['response'],usage,spoken=result.get('spoken_response'),clarification=result.get('clarification',False))
        except asyncio.CancelledError:
            self.store.update(task_id,'interrupted',error='Servidor encerrado. Revise os checkpoints.')
            raise
        except Exception as exc:
            if task_id in self.cancelled:
                await self.finish(task_id,'cancelled')
            else:
                error = ('Tempo limite da tarefa atingido. Confira os checkpoints antes de retomar.' if isinstance(exc,TimeoutError)
                         else redact(str(exc))[:1000] or type(exc).__name__)
                async with self.lock:
                    await self.finish(task_id,'failed',error,usage=self.store.get(task_id)['usage'],error=error)
        finally:
            self.runners.pop(task_id,None)
            self.cancelled.discard(task_id)
            self.local_runtime.cancelled.discard(task_id)
            await self.event(task_id,{'type':'task_updated','task':self.store.get(task_id)})

    async def cancel(self,task_id,reason='user'):
        task = self.store.get(task_id)
        if task_id not in self.runners:
            return task
        self.cancelled.add(task_id)
        self.store.input_trace(task_id,{'cancel_reason':reason})
        from core.audio_manager import audio_manager
        if self.speaking_task==task_id:await asyncio.to_thread(audio_manager.stop)
        self.store.update(task_id,'cancelling')
        await self.runtime.cancel(task_id)
        await self.local_runtime.cancel(task_id)
        return self.store.get(task_id)

    async def interrupt_session(self,session,reason='user'):
        interrupted=False
        for identifier in list(self.runners):
            if self.store.get(identifier)['session']==session:await self.cancel(identifier,reason=reason);interrupted=True
        if not interrupted and reason=='user':await self.acknowledge(session,'Senhor, não havia uma tarefa em andamento para cancelar.')

    async def resume(self,task_id):
        task = self.store.get(task_id)
        if task_id in self.runners:
            return task
        if task['state'] not in ('interrupted','failed','cancelled'):
            raise ValueError('Só tarefas interrompidas, canceladas ou falhas podem ser retomadas.')
        if any(t['state'] in ('started','failed') for t in task['tools']):
            raise ValueError('Há um efeito incerto/falho. Confira os resultados e envie uma nova instrução específica; retomada automática bloqueada.')
        self.store.update(task_id,'queued')
        self.finished.discard(task_id)
        self.runners[task_id] = asyncio.create_task(self.execute(task_id))
        return self.store.get(task_id)

    async def close(self):
        for runner in list(self.runners.values()):
            runner.cancel()
        await asyncio.gather(*list(self.runners.values()),return_exceptions=True)
        await self.local_runtime.close()
        await self.runtime.close()
