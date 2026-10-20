"""Hermes extension tools. All effects cross this policy/checkpoint boundary."""
import difflib
import json
import re
import subprocess
import sys
import time
from core.config import config
from core.safety import atomic_write, checked_path, digest, redact, file_lock
from core.task_store import TaskStore
from core.memory_obsidian import obsidian_memory
from core.basic_actions import BASIC_ACTIONS, BASIC_EFFECTS

from core.tool_registry import TOOLS, schema, validate
from core.operational_context import context_for
SCHEMA = schema()


def memory_operation(args):
    from tools.memory_tool import load_on_disk_store
    store = load_on_disk_store()
    action = args['action']
    target = args.get('target','user')
    if target not in ('user','memory'):
        raise ValueError('Destino de memória inválido.')
    if action == 'memory_list':
        return {t:store._entries_for(t) for t in ('user','memory')}
    text = redact(args.get('content',''))
    old = args.get('old_text','')
    if action == 'memory_add':
        source = args.get('source','user_statement')
        if source not in ('user_statement','document','observed'):
            raise ValueError('Inferências não podem se tornar fatos na memória essencial.')
        # Provenance is part of the native entry; exact duplicates remain idempotent.
        text = f'[{source}] {text}'
        result = store.add(target,text)
    elif action == 'memory_patch':
        result = store.patch(target,old,text)
    elif action == 'memory_remove':
        result = store.remove(target,old)
    else:
        raise ValueError('Operação de memória desconhecida.')
    if not result.get('success'):
        return {'error':result.get('error',str(result))}
    check = load_on_disk_store()
    entries = check._entries_for(target)
    verified = (any(text in e for e in entries) if action != 'memory_remove' else not any(old in e for e in entries))
    if not verified:
        raise IOError('Memória não confirmada após reabertura do armazenamento Hermes.')
    from core.task_store import now
    journal=config.DATA_DIR/'memory-events.json'
    with file_lock(journal):
        records=json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else []
        records.append({'time':now(),'action':action,'target':target,'old_text':redact(old),'content':text,'verified':True})
        atomic_write(journal,json.dumps(records[-200:],ensure_ascii=False,indent=2))
    return {'verified':True,'target':target,'entries':entries}

class ToolService:
    def __init__(self,task,emit=lambda *a:None,cancelled=lambda:False,store=None,external_dispatch=None,context=None):
        self.task = task
        self.emit = emit
        self.cancelled = cancelled
        self.store = store or TaskStore()
        self.calls = 0
        self.failures = 0
        self.failed_effects=0
        self.external_dispatch=external_dispatch
        try: session=self.store.get(task)['session']
        except KeyError: session='utility'
        self.context=context or context_for(session)
        self.deadline=time.monotonic()+config.TASK_TIMEOUT
        self.results=[]
        self.blocked=False

    def root(self,args):
        index = args.get('root',0)
        if not isinstance(index,int) or not 0 <= index < len(config.WORKSPACE_ROOTS):
            raise PermissionError('Diretório não autorizado.')
        return config.WORKSPACE_ROOTS[index]

    def execute(self,args,invocation_id=None):
        self.calls += 1
        from core.music_followup import followup_call
        followup=followup_call(self.store.get(self.task)['prompt']) if isinstance(args,dict) and args.get('action') in ('media','play_music','browser_search','browser_click') else None
        reference=self.store.get(self.task)['input'].get('media_reference',{})
        contextual_play=reference.get('accepted') and reference.get('operation') in ('play_existing','select_position')
        if contextual_play and isinstance(args,dict) and args.get('action') in ('play_music','browser_search','browser_click','media'):
            pending=self.context.music_goal.get('confirmation',{})
            args={'action':'media','check':'confirm_music','query':pending.get('id','')}
        elif followup and not self.context.music_intent.get('accepted'):args=followup
        volume_intent=None
        if isinstance(args,dict) and args.get('action')=='volume':
            from core.volume_intent import parse_volume
            volume_intent=parse_volume(self.store.get(self.task)['prompt'])
            if volume_intent and not volume_intent.question:args=volume_intent.call()
        # Resolve a start request before admission, so a mistaken resume cannot
        # require a pre-existing player or create two different checkpoints.
        if isinstance(args,dict) and args.get('action')=='media' and args.get('check')=='resume':
            from core.command_text import music_request,normalize_command
            from core.intents import media_intent
            source=self.store.get(self.task)['prompt']
            request=music_request(source,self.context)
            if request and request['query'] and not media_intent(normalize_command(source)) and not any(r.get('tool')=='play_music' and r.get('verified') for r in self.results):
                args={'action':'play_music','query':request['query']}
        if isinstance(args,dict) and args.get('action')=='play_music' and self.context.music_intent.get('accepted'):
            if self.context.music_intent.get('original_transcription')==self.store.get(self.task)['prompt']:
                args={**args,'query':self.context.music_intent['query']}
        checkpoint_id=None if followup or volume_intent and not volume_intent.question else invocation_id
        key = digest(json.dumps(args,sort_keys=True,ensure_ascii=False)+((':call:'+checkpoint_id) if checkpoint_id else ''))
        action = args.get('action','')
        if self.blocked:
            return {'error':'Resultado anterior não confirmado. Confira o estado antes de enviar nova instrução.','verified':False}
        if self.cancelled():
            return {'error':'Cancelado antes da execução.'}
        if time.monotonic()>self.deadline or self.calls > config.MAX_STEPS or self.failures >= 3:
            return {'error':'Orçamento de ferramentas atingido ou três falhas consecutivas. Interrompa e explique o bloqueio.'}
        effects = bool(TOOLS.get(action) and TOOLS[action].effect)
        previous_confirmation_recorder=getattr(self.context,'record_music_confirmation',None)
        try:
            if volume_intent and volume_intent.question:raise ValueError(volume_intent.question)
            args=validate(args)
            if action=='media' and args.get('check') in ('confirm_music','reject_music'):
                from core.music_followup import confirmation_reply
                trace=self.store.get(self.task)['input'].get('confirmation_reply',{})
                response='accept' if args['check']=='confirm_music' else 'reject'
                contextual_authorization=False
                if contextual_play and args['check']=='confirm_music':
                    from core.music_followup import reference_context,validate_reference
                    stored=self.store.get(self.task)['input'].get('music_intent',{})
                    checked=validate_reference(stored,self.store.get(self.task)['prompt'],reference.get('context') or {})
                    pending=self.context.music_goal.get('confirmation',{})
                    contextual_authorization=bool(checked.get('accepted') and reference_context(self.context).get('id')==reference.get('result_set_id') and
                        checked['candidate']['video_id']==pending.get('candidate',{}).get('video_id') and pending.get('authorization')=='context_candidate')
                if (contextual_play and not contextual_authorization) or (not contextual_authorization and confirmation_reply(self.store.get(self.task)['prompt'])!=response) or trace.get('id')!=args.get('query'):
                    raise ValueError('A confirmação não corresponde à escolha apresentada nesta conversa. Não iniciei outra busca.')
                confirmation_goal={**self.context.music_goal,'task_id':self.task}
                def record_confirmation(pending):
                    goal={**confirmation_goal,'confirmation':dict(pending)}
                    current=self.context.music_goal.get('confirmation',{})
                    if current.get('id')==pending['id'] and current.get('state')!='superseded':self.context.music_goal=goal
                    self.store.input_trace(self.task,{'music_goal':goal,'music_confirmation':dict(pending)})
                self.context.record_music_confirmation=record_confirmation
            if action=='play_music':
                queries=[]
                def record(query):
                    queries.append(query)
                    self.store.input_trace(self.task,{'final_search_query':query,'music_search_queries':list(queries)})
                self.context.record_music_query=record
            if action=='browser_select' and args['query'].startswith(('http://','https://')) and args['query'] not in self.store.get(self.task)['prompt']:
                raise ValueError('A seleção por URL exige o endereço explícito do usuário. Use o ID observado da aba.')
            if action=='volume' and args.get('scope')=='system':
                prompt=self.store.get(self.task)['prompt']
                if not re.search(r'(?i)\b(sistema|windows|computador|pc)\b',prompt):
                    raise ValueError('Volume do sistema exige pedido explícito. O padrão é o player da música.')
            self.emit('tool',{'action':action,'state':'running'})
            self.context.report=lambda value:self.emit('progress',value)
            if effects:
                cached = self.store.claim_tool(self.task,key,action)
                if cached is not None:
                    if action=='file_write':
                        path=checked_path(self.root(args),args['path'],True)
                        if digest(path.read_text(encoding='utf-8'))!=cached.get('sha256'):
                            raise RuntimeError('O arquivo mudou desde o checkpoint. Revise antes de retomar.')
                    self.results.append(cached)
                    return {**cached,'replayed_checkpoint':True,'note':'Evidência de uma execução anterior; a ação não foi repetida.'}
            started=time.monotonic()
            result = json.loads(redact(json.dumps(self._dispatch(args),ensure_ascii=False)))
            result['status']='failed' if result.get('error') else 'confirmed' if result.get('verified') is True and not result.get('launch_requested') else 'sent' if result.get('launch_requested') else 'unverified'
            result['tool']=action
            result['latency_seconds']=round(time.monotonic()-started,3)
            if result.get('music_selection'):self.store.input_trace(self.task,{'music_selection':result['music_selection']})
            if result.get('music_pipeline'):self.store.input_trace(self.task,{'music_pipeline':result['music_pipeline']})
            if result.get('music_goal'):self.store.input_trace(self.task,{'music_goal':result['music_goal'],'transcription_corrections':result.get('transcription_corrections',[])})
            if action=='volume' and result.get('volume_change'):
                result['volume_change'].update(text_received=self.store.get(self.task)['prompt'],
                    target_id='system' if args.get('scope')=='system' else self.context.media_tab_id)
                self.store.input_trace(self.task,{'volume_change':result['volume_change']})
            self.context.observe(action,result)
            if action=='open_target' and result.get('launch_requested'): self.context.application=args['path']
            self.results.append(result)
            if result.get('error') or result.get('verified') is False or result.get('needs_manual_verification'):
                self.blocked=True
            if result.get('error'):
                self.failures+=1
                if effects:self.failed_effects+=1
            if effects:
                self.store.finish_tool(self.task,key,result)
            if not result.get('error'): self.failures = 0
            self.emit('tool',{'action':action,'state':'done','result':result})
            return result
        except Exception as exc:
            self.failures += 1
            self.blocked=True
            if effects:self.failed_effects+=1
            result = {'error':redact(str(exc))[:1000],'verified':False,'status':'failed','tool':action}
            self.context.observe(action,result)
            self.results.append(result)
            if effects:
                # Only this call's admitted effect may be finalized. Existing uncertain
                # checkpoints are kept uncertain and may never be replayed as successful.
                with self.store.connect() as db:
                    db.execute("UPDATE tools SET state='failed',result=? WHERE task=? AND key=? AND state='started'",(json.dumps(result),self.task,key))
            self.emit('tool',{'action':action,'state':'failed','result':result})
            return result
        finally:
            self.context.record_music_confirmation=previous_confirmation_recorder

    def _dispatch(self,a):
        action = a['action']
        if self.external_dispatch and not action.startswith('memory_') and action not in ('history_search','skill_list','skill_read','skill_save'):
            return self.external_dispatch(a)
        if action in TOOLS and TOOLS[action].handler:
            return TOOLS[action].dispatch(a,self.cancelled,self.context)
        if action in BASIC_ACTIONS:
            from core.basic_tools import dispatch_basic
            return dispatch_basic(a,cancelled=self.cancelled)
        if action.startswith('memory_'):
            return memory_operation(a)
        if action == 'vault_search':
            return {'sources':obsidian_memory.search(a['query'])}
        if action == 'vault_read':
            return obsidian_memory.read(a['path'],a.get('start',1))
        if action == 'vault_write':
            return obsidian_memory.write(a['path'],a['content'],a.get('expected_hash'),a.get('source','user_statement'))
        if action == 'files_search':
            root = self.root(a)
            query = a.get('query','').casefold()
            results = []
            for path in root.rglob('*'):
                if len(results) >= 30:
                    break
                try:
                    path = checked_path(root,path.relative_to(root),True)
                    if path.stat().st_size > config.MAX_FILE_BYTES:
                        continue
                    if query in str(path.relative_to(root)).casefold():
                        results.append({'path':str(path.relative_to(root))})
                    elif path.suffix.lower() in ('.md','.txt','.py','.js','.ts','.json','.csv','.html','.css'):
                        for i,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
                            if query in line.casefold():
                                results.append({'path':str(path.relative_to(root)),'line':i,'excerpt':redact(line[:200])})
                                break
                except (OSError,UnicodeError,PermissionError):
                    continue
            return {'sources':results}
        if action == 'file_read':
            path = checked_path(self.root(a),a['path'],True)
            if path.stat().st_size > config.MAX_FILE_BYTES:
                raise ValueError('Arquivo excede 2 MB; selecione um trecho menor na origem.')
            if path.suffix.lower() == '.pdf':
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                page = max(1,a.get('start',1))
                content=reader.pages[page-1].extract_text() or ''
                if not content.strip():raise ValueError('Página sem texto extraível. OCR necessário; não foi executado.')
                return {'path':a['path'],'page':page,'content':redact(content)[:6000]}
            if path.suffix.lower() == '.docx':
                from docx import Document
                text = '\n'.join(p.text for p in Document(str(path)).paragraphs)
            else:
                text = path.read_text(encoding='utf-8')
            start = max(1,a.get('start',1))
            return {'path':a['path'],'line':start,'content':redact('\n'.join(text.splitlines()[start-1:start+59]))[:6000],'sha256':digest(text)}
        if action == 'file_write':
            path = checked_path(self.root(a),a['path'])
            text = redact(a['content'])
            if len(text.encode()) > config.MAX_FILE_BYTES:
                raise ValueError('Arquivo excede o limite.')
            if path.suffix.lower() not in ('.md','.txt','.py','.js','.ts','.json','.csv','.html','.css'):
                raise PermissionError('Tipo de arquivo não autorizado para gravação.')
            with file_lock(path):
                old = path.read_text(encoding='utf-8') if path.exists() else ''
                if path.exists() and digest(old) != a.get('expected_hash'):
                    raise ValueError('Arquivo mudou; leia e confira o sha256 antes de alterar.')
                if path.exists():
                    atomic_write(config.DATA_DIR/'revisions'/(digest(str(path))[:16]+'-'+digest(old)+'.txt'),old)
                sha = atomic_write(path,text)
            diff = ''.join(difflib.unified_diff(old.splitlines(True),text.splitlines(True),fromfile=a['path'],tofile=a['path']))[:3000]
            return {'verified':True,'path':a['path'],'sha256':sha,'diff':diff}
        if action == 'run_check':
            if a.get('check') not in ('unittest','compile'):
                raise ValueError('Verificações permitidas: unittest, compile.')
            root = self.root(a)
            relative = a.get('path','')
            cwd = (root/relative).resolve()
            if not cwd.is_relative_to(root) or not cwd.is_dir():
                raise PermissionError('Diretório não autorizado.')
            if cwd!=root:checked_path(root,relative)
            cmd = [sys.executable,'-m','unittest','discover','-v'] if a.get('check') == 'unittest' else [sys.executable,'-m','compileall','-q','-x',r'(^|[\\/])(\.[^\\/]+|node_modules|__pycache__)([\\/]|$)','.']
            # Tests execute project code. They are scoped by trusted root configuration,
            # not an OS sandbox. No secrets are passed to the command environment.
            import os,tempfile
            env = {k:v for k,v in os.environ.items() if k.upper() in ('PATH','SYSTEMROOT','WINDIR','TEMP','TMP','COMSPEC','PATHEXT','USERPROFILE','LOCALAPPDATA','APPDATA')}
            env['PYTHONIOENCODING'] = 'utf-8'
            with tempfile.TemporaryFile() as output:
                proc = subprocess.Popen(cmd,cwd=cwd,env=env,stdout=output,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                deadline = time.monotonic()+30
                while proc.poll() is None:
                    if self.cancelled() or time.monotonic()>deadline:
                        import psutil
                        parent = psutil.Process(proc.pid)
                        for child in parent.children(recursive=True):
                            child.kill()
                        parent.kill()
                        proc.wait(timeout=5)
                        raise TimeoutError('Comando interrompido ou limite de 30 segundos atingido.')
                    time.sleep(.1)
                output.seek(0)
                data = output.read(6000).decode('utf-8',errors='replace')
            match=re.search(r'Ran (\d+) tests?',data)
            count=int(match.group(1)) if match else 0
            valid=proc.returncode==0 and (a['check']!='unittest' or count>0)
            return {'verified':valid,'exit_code':proc.returncode,'check':a['check'],'tests_run':count,'output':redact(data),
                    'error':None if valid else 'Verificação falhou ou nenhum teste foi executado.'}
        if action == 'web_search':
            from ddgs import DDGS
            results = list(DDGS(timeout=10).text(a['query'],max_results=4))
            return {'sources':[{'title':r.get('title'),'url':r.get('href'),'excerpt':r.get('body','')[:700]} for r in results]}
        if action == 'system_status':
            from core.system_monitor import system_monitor
            metrics=system_monitor.get_metrics()
            return {**metrics,'verified':True,'message':f"Processador em {metrics['cpu_percent']:.0f}%. Memória em {metrics['ram_percent']:.0f}%, com {metrics['ram_used_gb']} de {metrics['ram_total_gb']} GB em uso. Disco com {metrics['disk_free_gb']} GB livres. Tempo ligado: {metrics['uptime']}."}
        if action == 'open_target':
            from core.automation import automation_service
            ok,message=automation_service.open_target(a['path'])
            return {'verified':ok,'launch_requested':ok,'message':message}
        if action == 'screenshot':
            from core.automation import automation_service
            return automation_service.take_screenshot()
        if action in ('macro_list','macro_run'):
            macros=json.loads(config.COMMANDS_FILE.read_text(encoding='utf-8')).get('custom_commands',[])
            if action=='macro_list':return {'macros':[m.get('trigger','') for m in macros]}
            macro=next((m for m in macros if m.get('trigger','').casefold()==a.get('query','').casefold()),None)
            if not macro:raise ValueError('Macro não encontrada. Consulte macro_list.')
            targets=macro.get('targets',[]) if macro.get('action_type')=='open_multiple' else [macro.get('target')]
            if macro.get('action_type') not in ('open_multiple','open_app','open_folder','open_url') or not targets:
                raise ValueError('Tipo de macro não autorizado.')
            from core.automation import automation_service
            results=[]
            for target in targets[:6]:
                ok,message=automation_service.open_target(target)
                results.append({'target':target,'launch_requested':ok,'message':message})
            return {'verified':all(r['launch_requested'] for r in results),'results':results,'message':'Solicitações de abertura da macro enviadas ao Windows; reprodução não foi verificada.'}
        if action == 'skill_list':
            root=config.HERMES_HOME/'skills'
            query=a.get('query','').casefold()
            return {'skills':[str(p.parent.relative_to(root)) for p in root.rglob('SKILL.md') if query in str(p.parent.relative_to(root)).casefold()][:30]}
        if action == 'skill_read':
            path=checked_path(config.HERMES_HOME/'skills',a['path']+'/SKILL.md',True)
            return {'path':str(path.relative_to(config.HERMES_HOME)),'content':redact(path.read_text(encoding='utf-8'))[:6000]}
        if action == 'history_search':
            from hermes_state import SessionDB
            db = SessionDB()
            try:
                return {'results':db.search_messages(a['query'],limit=5)}
            finally:
                db.close()
        if action == 'skill_save':
            evidence = self.store.get(a['evidence_task'])
            verified = [json.loads(t['result']) for t in evidence['tools'] if t['state']=='done' and t['result']]
            if evidence['state']!='completed' or not any(r.get('verified') and r.get('exit_code')==0 and r.get('check')=='unittest' and r.get('tests_run',0)>0 for r in verified):
                raise ValueError('Procedimento exige tarefa concluída com teste executado e verificado.')
            name = a['path']
            if not re.fullmatch(r'[a-z][a-z0-9-]{2,60}',name):
                raise ValueError('Nome de skill inválido.')
            text = redact(a['content'])
            if not text.startswith('---') or len(text)>12000:
                raise ValueError('Skill deve conter frontmatter e até 12000 caracteres.')
            path = checked_path(config.HERMES_HOME/'skills',name+'/SKILL.md')
            if path.exists():
                raise ValueError('Skill existente: revise manualmente antes de substituir.')
            sha = atomic_write(path,text+'\n\nEvidência JARVIS: '+evidence['id']+'\n')
            return {'verified':True,'skill':name,'sha256':sha}
        raise ValueError('Ferramenta indisponível: '+action)
