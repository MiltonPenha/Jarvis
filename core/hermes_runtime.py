"""Official PM activation, subprocess lifecycle and provider discovery."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import httpx
from core.config import config, provider_key
from core.safety import atomic_write, redact

RUNTIME_FILE = config.BASE_DIR / '.runtime/runtime.json'

def prepare_runtime():
    env = os.environ.copy()
    env.update(HERMES_HOME=str(config.HERMES_HOME),HERMES_RUNTIME_DIR=str(config.BASE_DIR/'.runtime/tools'),PYTHONPATH=str(config.HERMES_SOURCE),PYTHONIOENCODING='utf-8')
    output = subprocess.check_output([sys.executable,'-m','pm.environments'],env=env,text=True,encoding='utf-8',timeout=30)
    values = json.loads(output)
    selected = {k:v for k,v in values.items() if k in ('PATH','PYTHONPATH','__HERMES_ACTIVATED')}
    # Use the committed PM venv interpreter. A bare PM store Python refuses a
    # separate HERMES_HOME (including isolated test profiles) with no install facts.
    packages = [Path(p) for p in values.get('PYTHONPATH','').split(os.pathsep) if Path(p).name=='site-packages']
    candidates = [p.parent.parent / ('Scripts/python.exe' if os.name=='nt' else 'bin/python') for p in packages]
    selected['executable'] = next((str(p) for p in candidates if p.is_file()),shutil.which('python',path=values['PATH']))
    if not selected['executable']:
        raise RuntimeError('Execute scripts/setup.ps1 para preparar o Hermes.')
    atomic_write(RUNTIME_FILE,json.dumps(selected))
    return selected

def runtime():
    if not RUNTIME_FILE.exists():
        raise RuntimeError('Hermes não preparado. Execute scripts/setup.ps1.')
    data = json.loads(RUNTIME_FILE.read_text(encoding='utf-8'))
    if not Path(data['executable']).is_file():
        raise RuntimeError('Runtime Hermes ausente. Execute scripts/setup.ps1 novamente.')
    return data

def worker_env():
    prepared = runtime()
    env = os.environ.copy()
    env.update({k:v for k,v in prepared.items() if k!='executable'})
    env['PYTHONPATH'] = str(config.BASE_DIR)+os.pathsep+env['PYTHONPATH']
    env.update(HERMES_HOME=str(config.HERMES_HOME),JARVIS_HERMES_HOME=str(config.HERMES_HOME),JARVIS_DATA_DIR=str(config.DATA_DIR),
               HERMES_RUNTIME_DIR=str(config.BASE_DIR/'.runtime/tools'),PYTHONIOENCODING='utf-8',PYTHONUTF8='1',HERMES_API_CALL_TIMEOUT='45')
    return env

def ensure_hermes_config():
    path = config.HERMES_HOME / 'config.yaml'
    content = '''# Managed by JARVIS: provider selection in settings.json; limits in .env.
agent:
  api_max_retries: 2
  auto_recovery_cycles: 0
tools:
  tool_search:
    enabled: "off"
compression:
  enabled: false
memory:
  memory_char_limit: 2200
  user_char_limit: 1375
auxiliary:
  background_review:
    enabled: false
'''
    if not path.exists() or path.read_text(encoding='utf-8') != content:
        atomic_write(path,content)

async def terminate_tree(proc):
    if proc.returncode is not None:
        return
    import psutil
    try:
        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
    except psutil.NoSuchProcess:
        pass
    await proc.wait()

class HermesRuntime:
    def __init__(self):
        self.processes = {}

    async def run(self,request,on_event=None,timeout=None):
        ensure_hermes_config()
        prepared = runtime()
        proc = await asyncio.create_subprocess_exec(config.HERMES_PYTHON or prepared['executable'],str(config.BASE_DIR/'core/hermes_worker.py'),
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,
            env=worker_env(),cwd=str(config.BASE_DIR),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),limit=1_000_000)
        key = request.get('id','utility-'+str(proc.pid))
        self.processes[key] = proc
        proc.stdin.write((json.dumps(request,ensure_ascii=False)+'\n').encode('utf-8'))
        await proc.stdin.drain()
        result = None
        async def consume():
            nonlocal result
            while line := await proc.stdout.readline():
                message = json.loads(line)
                if message['type']=='error':
                    data = message['data']
                    raise RuntimeError(f"Hermes {data.get('category','error')}: {data['error']}")
                if message['type']=='result':
                    result = message['data']
                elif message['type']=='tool_request':
                    from core.jarvis_tools import ToolService
                    data=message['data']
                    # The official Hermes handler owns admission/checkpoints; host
                    # execution uses the JARVIS dependencies, never mutates Hermes's env.
                    host=ToolService(request['id'],cancelled=lambda:proc.returncode is not None)
                    try:
                        output=await asyncio.to_thread(host._dispatch,data['args'])
                    except Exception as exc:
                        output={'error':redact(str(exc))[:1000],'verified':False}
                    if proc.returncode is None:
                        proc.stdin.write((json.dumps({'reply':data['key'],'result':output},ensure_ascii=False)+'\n').encode('utf-8'))
                        await proc.stdin.drain()
                elif on_event:
                    await on_event(message)
            await proc.wait()
        try:
            await asyncio.wait_for(consume(),timeout or config.TASK_TIMEOUT+15)
            if result is None:
                raise RuntimeError('Hermes encerrou sem um resultado verificável.')
            return result
        finally:
            self.processes.pop(key,None)
            await terminate_tree(proc)

    async def cancel(self,task):
        proc = self.processes.get(task)
        if proc and proc.returncode is None:
            try:
                proc.stdin.write(b'cancel\n')
                await proc.stdin.drain()
                await asyncio.wait_for(proc.wait(),5)
            except (TimeoutError,BrokenPipeError,ConnectionResetError):
                await terminate_tree(proc)

    async def close(self):
        for key in list(self.processes):
            await self.cancel(key)

async def list_models(provider):
    key = provider_key(provider)
    if not key:
        raise ValueError('Configure OPENAI_API_KEY ou GEMINI_API_KEY no backend e reinicie.')
    url = 'https://api.openai.com/v1/models' if provider=='openai-api' else 'https://generativelanguage.googleapis.com/v1beta/models'
    headers = {'Authorization':'Bearer '+key} if provider=='openai-api' else {'x-goog-api-key':key}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url,headers=headers,params={'pageSize':1000} if provider=='gemini' else None)
    except httpx.TimeoutException as exc:
        raise ValueError(f'{provider}: tempo limite ao consultar o catálogo. Tente novamente.') from exc
    except httpx.NetworkError as exc:
        raise ValueError(f'{provider}: rede indisponível ao consultar o catálogo.') from exc
    if response.status_code!=200:
        raise ValueError(f'{provider}: HTTP {response.status_code}. Verifique a credencial, acesso e limites no provedor.')
    data = response.json()
    if provider=='openai-api':
        models = [m['id'] for m in data['data'] if m['id'].startswith(('gpt-','o1','o3','o4')) and not any(x in m['id'] for x in ('audio','tts','transcribe','realtime','search','image'))]
    else:
        models = [m['name'].removeprefix('models/') for m in data.get('models',[]) if 'generateContent' in m.get('supportedGenerationMethods',[])]
    return sorted(models)

if __name__=='__main__':
    prepare_runtime()
    print('Runtime Hermes selecionado via PM; nenhum segredo foi gravado.')
