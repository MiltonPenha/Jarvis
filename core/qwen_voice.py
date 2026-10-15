"""Cached CPU-only speech worker, with cancellable IPC and bounded system RAM."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import psutil

from core.config import config


class QwenVoiceError(ValueError):
    pass


class QwenVoiceCancelled(Exception):
    pass


class QwenVoice:
    def __init__(self):
        self._request_lock = threading.RLock()
        self._process_lock = threading.Lock()
        self._process = None
        self._channel = None
        self._pid = None
        self._ready = False
        self._idle_timer = None
        self.last_synthesis = {}

    def status(self):
        with self._process_lock:
            ready = self._ready and self._process is not None and self._process.poll() is None
            pid = self._pid
        try:
            rss = round(psutil.Process(pid).memory_info().rss/2**20, 1) if pid and ready else 0
        except psutil.Error:
            rss = 0
        return {'ready':ready, 'device':'CPU', 'threads':config.QWEN_THREADS, 'rss_mib':rss,
                'reference_id':'a5b93aeddcc948c19ea04f0afe9d178c', 'last_synthesis':self.last_synthesis}

    def close(self):
        with self._process_lock:
            process = self._process
            self._process = None
            self._ready = False
            self._pid = None
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
        if process is not None:
            try:
                owner = psutil.Process(process.pid)
                for member in owner.children(recursive=True)+[owner]:
                    try:member.terminate()
                    except psutil.NoSuchProcess:pass
            except psutil.NoSuchProcess:
                pass
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            if process.stdin:
                process.stdin.close()

    def _idle(self):
        if self._request_lock.acquire(blocking=False):
            try:self.close()
            finally:self._request_lock.release()

    def _release_later(self):
        with self._process_lock:
            if self._idle_timer:self._idle_timer.cancel()
            self._idle_timer = threading.Timer(config.QWEN_IDLE_SECONDS, self._idle)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _wait(self, channel, cancel, deadline):
        while True:
            if cancel is not None and cancel.is_set():raise QwenVoiceCancelled()
            if time.monotonic() > deadline:raise QwenVoiceError('A voz local demorou demais. Tente uma resposta mais curta.')
            if psutil.virtual_memory().available < 1.5*2**30:
                raise QwenVoiceError('Pouca RAM do sistema disponível para gerar a voz local.')
            if self._pid:
                try:
                    if psutil.Process(self._pid).memory_info().rss > 3300*2**20:
                        raise QwenVoiceError('A voz local ultrapassou o limite de RAM do sistema.')
                except psutil.NoSuchProcess:
                    if cancel is not None and cancel.is_set():raise QwenVoiceCancelled()
                    raise QwenVoiceError('O processo de voz local foi encerrado.') from None
            try:event = channel.get(timeout=.05)
            except queue.Empty:continue
            if cancel is not None and cancel.is_set():raise QwenVoiceCancelled()
            if event.get('state') == 'boot':
                self._pid = event['pid']
                continue
            if event.get('state') in ('failed','closed'):
                raise QwenVoiceError('A síntese Qwen local falhou. Confira os arquivos da voz e tente uma frase curta.')
            return event

    def _prepare(self, cancel):
        if cancel is not None and cancel.is_set():raise QwenVoiceCancelled()
        with self._process_lock:
            if self._ready and self._process is not None and self._process.poll() is None:
                return self._channel
        self.close()
        if not (config.BASE_DIR/'.runtime/voice-lab/model/manifest.json').is_file():
            raise QwenVoiceError('Voz Qwen local não preparada. Consulte docs/AUDIO_LOCAL.md.')
        env = {k:v for k,v in os.environ.items() if not any(w in k.upper() for w in ('API_KEY','TOKEN','SECRET','PASSWORD'))}
        env.update(CUDA_VISIBLE_DEVICES='-1', PYTHONIOENCODING='utf-8', HF_HUB_OFFLINE='1',
                   TRANSFORMERS_OFFLINE='1', USE_TORCH='0')
        channel = queue.Queue()
        with self._process_lock:
            process = subprocess.Popen([sys.executable, str(config.BASE_DIR/'core/qwen_voice_worker.py'), str(config.QWEN_THREADS)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                cwd=str(config.BASE_DIR), env=env, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self._process = process
            self._channel = channel
        def read():
            with process.stdout:
                for line in process.stdout:
                    try:channel.put(json.loads(line))
                    except json.JSONDecodeError:pass
            channel.put({'state':'closed'})
        threading.Thread(target=read, daemon=True).start()
        event = self._wait(channel, cancel, time.monotonic()+45)
        if event.get('state') != 'ready' or event.get('providers') != ['CPUExecutionProvider']:
            raise QwenVoiceError('O motor de voz não confirmou execução exclusiva na CPU.')
        self._ready = True
        return channel

    def prepare(self, cancel=None):
        with self._request_lock:
            try:
                self._prepare(cancel)
                self._release_later()
            except BaseException:
                self.close()
                raise

    def synthesize(self, text, path, cancel=None):
        if not isinstance(text,str) or not 0 < len(text) <= 300:
            raise QwenVoiceError('A voz Qwen aceita até 300 caracteres por frase.')
        with self._request_lock:
            try:
                channel = self._prepare(cancel)
                if cancel is not None and cancel.is_set():raise QwenVoiceCancelled()
                self._process.stdin.write(json.dumps({'text':text, 'path':str(Path(path).resolve())},ensure_ascii=True)+'\n')
                self._process.stdin.flush()
                event = self._wait(channel, cancel, time.monotonic()+120)
                if event.get('state') != 'completed' or not Path(path).is_file() or Path(path).stat().st_size <= 44:
                    raise QwenVoiceError('A voz local não retornou áudio válido.')
                self.last_synthesis = {'seconds':event['seconds'], 'characters':len(text)}
                self._release_later()
            except (BrokenPipeError, OSError):
                self.close()
                Path(path).unlink(missing_ok=True)
                if cancel is not None and cancel.is_set():raise QwenVoiceCancelled() from None
                raise QwenVoiceError('O processo de voz foi encerrado. Tente novamente.') from None
            except BaseException:
                self.close()
                Path(path).unlink(missing_ok=True)
                if cancel is not None and cancel.is_set():raise QwenVoiceCancelled() from None
                raise


qwen_voice = QwenVoice()
