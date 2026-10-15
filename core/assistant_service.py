"""Single serialized entry point for text/voice and durable Hermes tasks."""
import asyncio
import time
import uuid
from core.config import config,settings,provider_key
from core.hermes_runtime import HermesRuntime
from core.task_store import TaskStore
from core.safety import redact

class AssistantService:
    def __init__(self,broadcast):
        self.broadcast = broadcast
        self.store = TaskStore()
        self.runtime = HermesRuntime()
        self.lock = asyncio.Lock()
        self.runners = {}
        self.cancelled = set()

    async def submit(self,command,session,task_id=None):
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
        if usage['tasks']>=config.MAX_DAILY_TASKS or usage['tokens']>=config.MAX_DAILY_TOKENS:
            raise ValueError('Orçamento diário atingido. Ajuste os limites no backend.')
        if len(self.runners)>=5:
            raise ValueError('Fila cheia. Aguarde ou cancele uma tarefa.')
        self.store.create(task_id,session,command)
        self.runners[task_id] = asyncio.create_task(self.execute(task_id))
        return self.store.get(task_id)

    async def event(self,task_id,event):
        event['task_id'] = task_id
        event['session'] = self.store.get(task_id)['session']
        await self.broadcast(event)

    async def execute(self,task_id):
        try:
            async with self.lock:
                if task_id in self.cancelled:
                    return
                task = self.store.get(task_id)
                s = settings()
                if self.store.daily_usage()['tokens']>=config.MAX_DAILY_TOKENS:
                    raise ValueError('Orçamento diário de tokens atingido antes de iniciar a tarefa da fila.')
                self.store.update(task_id,'running')
                await self.event(task_id,{'type':'state','state':'PROCESSING'})
                await self.event(task_id,{'type':'user_command','text':task['prompt']})
                if not s['model']:
                    raise ValueError('Escolha um modelo em Configurações. Configure uma chave válida no backend e use Consultar modelos.')
                if not provider_key(s['provider']):
                    raise ValueError('Credencial ausente. Configure OPENAI_API_KEY ou GEMINI_API_KEY no backend e reinicie.')
                started = time.monotonic()
                first_event = None
                async def progress(event):
                    nonlocal first_event
                    if first_event is None:
                        first_event = time.monotonic()-started
                    if event['type']=='tool':
                        await self.event(task_id,{'type':'state','state':'EXECUTING'})
                    await self.event(task_id,event)
                request = {'id':task_id,'session':task['session'],'command':task['prompt'],'settings':s}
                try:
                    result = await self.runtime.run(request,progress,timeout=config.TASK_TIMEOUT)
                except RuntimeError as exc:
                    # Provider failures before tool admission may use the explicit
                    # fallback. Configuration, cancellation and timeouts fail closed.
                    if not s.get('fallback_provider') or not s.get('fallback_model') or self.store.get(task_id)['tools'] or task_id in self.cancelled:
                        raise
                    result={'error':str(exc)}
                # A configured fallback can run only before any effect was admitted.
                # No full-turn replay is ever attempted after tool execution.
                prior_usage=None
                if result.get('error') and s.get('fallback_provider') and s.get('fallback_model') and not self.store.get(task_id)['tools']:
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
                    self.store.update(task_id,'cancelled',usage=usage)
                    await self.event(task_id,{'type':'state','state':'CANCELLED'})
                    return
                if result.get('error') or not result.get('response'):
                    self.store.update(task_id,'failed',usage=usage,error=result.get('error'))
                    raise RuntimeError(result.get('error') or 'Hermes não retornou resposta.')
                if result.get('effect_errors') or any(t['state']=='failed' for t in self.store.get(task_id)['tools']):
                    self.store.update(task_id,'failed',usage=usage,error='Uma ferramenta falhou; consulte os checkpoints.')
                    raise RuntimeError('A tarefa terminou com falha de ferramenta. Consulte os checkpoints; nenhum sucesso integral foi confirmado.')
                self.store.update(task_id,'completed',result=result['response'],usage=usage)
                await self.event(task_id,{'type':'jarvis_response','response':result['response'],'meta':{'usage':usage}})
                if s['speech_enabled']:
                    from core.audio_manager import audio_manager
                    spoken = await asyncio.to_thread(audio_manager.speak,result['response'])
                    if spoken.get('error'):
                        await self.event(task_id,{'type':'notice','text':spoken['error']})
                await self.event(task_id,{'type':'state','state':'CANCELLED' if task_id in self.cancelled else 'COMPLETED'})
        except asyncio.CancelledError:
            self.store.update(task_id,'interrupted',error='Servidor encerrado. Revise os checkpoints.')
            raise
        except Exception as exc:
            if task_id in self.cancelled:
                self.store.update(task_id,'cancelled')
                await self.event(task_id,{'type':'state','state':'CANCELLED'})
            else:
                error = ('Tempo limite da tarefa atingido. Confira os checkpoints antes de retomar.' if isinstance(exc,TimeoutError)
                         else redact(str(exc))[:1000] or type(exc).__name__)
                self.store.update(task_id,'failed',error=error)
                await self.event(task_id,{'type':'notice','text':error})
                await self.event(task_id,{'type':'state','state':'FAILED'})
        finally:
            self.runners.pop(task_id,None)
            self.cancelled.discard(task_id)
            await self.event(task_id,{'type':'task_updated','task':self.store.get(task_id)})

    async def cancel(self,task_id):
        task = self.store.get(task_id)
        if task_id not in self.runners:
            return task
        self.cancelled.add(task_id)
        from core.audio_manager import audio_manager
        audio_manager.stop()
        self.store.update(task_id,'cancelling')
        await self.runtime.cancel(task_id)
        self.store.update(task_id,'cancelled')
        await self.event(task_id,{'type':'state','state':'CANCELLED'})
        return self.store.get(task_id)

    async def resume(self,task_id):
        task = self.store.get(task_id)
        if task_id in self.runners:
            return task
        if task['state'] not in ('interrupted','failed','cancelled'):
            raise ValueError('Só tarefas interrompidas, canceladas ou falhas podem ser retomadas.')
        if any(t['state'] in ('started','failed') for t in task['tools']):
            raise ValueError('Há um efeito incerto/falho. Confira os resultados e envie uma nova instrução específica; retomada automática bloqueada.')
        self.store.update(task_id,'queued')
        self.runners[task_id] = asyncio.create_task(self.execute(task_id))
        return self.store.get(task_id)

    async def close(self):
        await self.runtime.close()
        for runner in list(self.runners.values()):
            runner.cancel()
        await asyncio.gather(*list(self.runners.values()),return_exceptions=True)
