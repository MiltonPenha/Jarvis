"""Private, CPU-only Ollama worker. Never connects to the user's Ollama service."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import threading
import httpx
from core.config import config

MODEL = 'qwen3:1.7b'
BASE_URL = 'http://127.0.0.1:11439'


class LocalModel:
    def __init__(self):
        self.process = None
        self.lock = asyncio.Lock()
        self.last_metrics = {}
        self.lifecycle_lock=threading.RLock()
        self.worker_identity=None

    @property
    def worker_record(self):return config.DATA_DIR/'local-model-worker.json'

    def _recover_orphan(self,executable):
        """Recover only this project's recorded worker with an absent owner."""
        import psutil
        try:
            record=json.loads(self.worker_record.read_text(encoding='utf-8'))
            worker=psutil.Process(record['pid'])
            if worker.create_time()!=record['created_at']:return False
            if Path(worker.exe()).resolve()!=Path(executable).resolve():return False
            environment=worker.environ()
            if environment.get('OLLAMA_HOST')!='127.0.0.1:11439':return False
            if Path(environment.get('OLLAMA_MODELS','')).resolve()!=(config.DATA_DIR/'models/ollama').resolve():return False
            try:
                owner=psutil.Process(record['owner_pid'])
                if owner.create_time()==record['owner_created_at']:return False
            except psutil.NoSuchProcess:pass
            children=worker.children(recursive=True)
            for process in children+[worker]:
                try:process.terminate()
                except psutil.NoSuchProcess:pass
            _,alive=psutil.wait_procs(children+[worker],timeout=4)
            for process in alive:
                try:process.kill()
                except psutil.NoSuchProcess:pass
            _,alive=psutil.wait_procs(alive,timeout=3)
            if alive:return False
            if json.loads(self.worker_record.read_text(encoding='utf-8'))==record:self.worker_record.unlink()
            return True
        except (OSError,ValueError,KeyError,TypeError,psutil.Error):return False

    def start(self):
        with self.lifecycle_lock:
            from core.safety import file_lock
            with file_lock(self.worker_record):self._start()

    def _start(self):
        if self.process and self.process.poll() is None:
            return
        executable = shutil.which('ollama') or str(Path(os.getenv('LOCALAPPDATA', ''))/'Programs/Ollama/ollama.exe')
        if not Path(executable).is_file():
            raise RuntimeError('Ollama não encontrado. Instale o runtime antes de preparar o modelo local.')
        import socket
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', 11439)) == 0:
                if not self._recover_orphan(executable):
                    raise RuntimeError('A porta privada 11439 está ocupada por um processo ativo ou não identificado. Nenhum serviço existente foi utilizado.')
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',11439))==0:raise RuntimeError('A porta privada 11439 ainda está ocupada.')
        env = os.environ.copy()
        for key in list(env):
            if any(word in key.upper() for word in ('API_KEY','TOKEN','PASSWORD','SECRET')):
                env.pop(key,None)
        # Both discovery and per-request placement disable GPU. No global settings change.
        env.update(OLLAMA_HOST='127.0.0.1:11439', OLLAMA_MODELS=str(config.DATA_DIR/'models/ollama'),
                   CUDA_VISIBLE_DEVICES='-1', ROCR_VISIBLE_DEVICES='-1', GGML_VK_VISIBLE_DEVICES='-1',
                   OLLAMA_VULKAN='false', OLLAMA_NO_CLOUD='1', OLLAMA_NUM_PARALLEL='1',
                   OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_CONTEXT_LENGTH='4096', OLLAMA_KEEP_ALIVE='120s',
                   OLLAMA_ORIGINS='http://127.0.0.1:11439')
        logs = config.DATA_DIR/'logs'; logs.mkdir(parents=True, exist_ok=True)
        with (logs/'local-model.log').open('ab') as log:
            self.process = subprocess.Popen([executable, 'serve'], env=env, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        import psutil
        from core.safety import atomic_write
        self.worker_identity={'pid':self.process.pid,'created_at':psutil.Process(self.process.pid).create_time(),
            'owner_pid':os.getpid(),'owner_created_at':psutil.Process(os.getpid()).create_time()}
        try:atomic_write(self.worker_record,json.dumps(self.worker_identity))
        except OSError:
            self.stop()
            raise RuntimeError('Não foi possível registrar o processo da IA local para encerramento seguro.')
        deadline = time.monotonic()+25
        with httpx.Client(base_url=BASE_URL, trust_env=False, timeout=2) as client:
            while time.monotonic()<deadline:
                if self.process.poll() is not None:
                    raise RuntimeError('O runtime local encerrou. Consulte .data/logs/local-model.log.')
                try:
                    if client.get('/api/version').is_success:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
        self.stop()
        raise TimeoutError('O runtime local não iniciou em 25 segundos.')

    def prepared(self):
        return (config.DATA_DIR/'models/ollama/manifests/registry.ollama.ai/library/qwen3/1.7b').is_file()

    async def plan(self, prompt, schema, max_tokens=600):
        async with self.lock:
            if not self.prepared():
                raise RuntimeError('Modelo local não preparado. Execute scripts/setup_local_model.py.')
            import psutil
            if psutil.virtual_memory().available<2.5*2**30:
                raise RuntimeError('Menos de 2,5 GB de RAM disponíveis. Libere memória antes de carregar o modelo local.')
            # Runtime validates string lengths. Large maxLength grammar repetitions
            # are unsupported by older Ollama builds, so omit them from decoding.
            schema=json.loads(json.dumps(schema))
            def grammar_schema(value):
                if isinstance(value,dict):
                    value.pop('maxLength',None)
                    for item in value.values(): grammar_schema(item)
                elif isinstance(value,list):
                    for item in value: grammar_schema(item)
            grammar_schema(schema)
            await asyncio.to_thread(self.start)
            started = time.monotonic()
            async with httpx.AsyncClient(base_url=BASE_URL, trust_env=False, timeout=110) as client:
                response = await client.post('/api/chat', json={
                    'model':MODEL, 'stream':False, 'think':False, 'keep_alive':'120s', 'format':schema,
                    'messages':[{'role':'system','content':prompt[0]}, {'role':'user','content':prompt[1]}],
                    'options':{'num_gpu':0, 'num_thread':6, 'num_ctx':4096, 'num_predict':max(16,min(600,max_tokens)), 'temperature':0}})
                response.raise_for_status()
                result = response.json()
                self.last_metrics = {'seconds':round(time.monotonic()-started, 3),
                    'input_tokens':result.get('prompt_eval_count', 0), 'output_tokens':result.get('eval_count', 0),
                    'load_seconds':round(result.get('load_duration', 0)/1e9, 3)}
                loaded = (await client.get('/api/ps')).json().get('models', [])
                if any(m.get('size_vram', 0)>0 for m in loaded):
                    # An explicit guard: never continue with a model placed in VRAM.
                    await client.post('/api/generate', json={'model':MODEL, 'keep_alive':0})
                    raise RuntimeError('O runtime tentou utilizar VRAM. Modelo descarregado; execução bloqueada.')
                self.last_metrics['vram_bytes'] = sum(m.get('size_vram', 0) for m in loaded)
                return json.loads(result['message']['content'])

    def status(self):
        return {'model':MODEL, 'prepared':self.prepared(), 'cpu_only':True, 'threads':6,
                'running':bool(self.process and self.process.poll() is None), 'last_inference':self.last_metrics}

    def stop(self):
        with self.lifecycle_lock:
            self._stop()

    def _stop(self):
        if self.process and self.process.poll() is None:
            import psutil
            try:
                parent = psutil.Process(self.process.pid)
                children = parent.children(recursive=True)
                for child in children:
                    try: child.terminate()
                    except psutil.NoSuchProcess: pass
                parent.terminate()
                _, alive = psutil.wait_procs(children+[parent], timeout=4)
                for process in alive:
                    try: process.kill()
                    except psutil.NoSuchProcess: pass
            except psutil.NoSuchProcess:
                pass
            self.process.wait(timeout=5)
        self.process = None
        if self.worker_identity:
            try:
                if json.loads(self.worker_record.read_text(encoding='utf-8'))==self.worker_identity:self.worker_record.unlink()
            except (OSError,ValueError):pass
        self.worker_identity=None


local_model = LocalModel()
