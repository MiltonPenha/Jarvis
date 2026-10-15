"""JSONL voice process: no network, API credentials, GPU, recording or playback."""
import contextlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def send(**value):
    print(json.dumps(value, ensure_ascii=True), flush=True)


def main():
    import psutil
    process = psutil.Process()
    if os.name == 'nt':
        process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    import socket
    def offline(*args, **kwargs):
        raise RuntimeError('A voz Qwen funciona sem rede.')
    socket.socket.connect = offline
    socket.create_connection = offline
    send(state='boot', pid=os.getpid())
    try:
        start = time.monotonic()
        with contextlib.redirect_stdout(sys.stderr):
            from core.qwen_cpu_engine import QwenCpuEngine
            engine = QwenCpuEngine(ROOT/'.runtime/voice-lab', int(sys.argv[1]))
        send(state='ready', providers=sorted({p for s in engine.sessions for p in s.get_providers()}),
             load_seconds=round(time.monotonic()-start, 3))
        for line in sys.stdin:
            request = json.loads(line)
            text = request['text']
            if not isinstance(text, str) or not 0 < len(text) <= 300:
                raise ValueError('Texto de voz fora do limite permitido.')
            start = time.monotonic()
            with contextlib.redirect_stdout(sys.stderr):
                engine.synthesize(text, Path(request['path']))
            send(state='completed', seconds=round(time.monotonic()-start, 3))
    except Exception:
        # Do not echo user speech, arbitrary tracebacks, paths, or provider messages.
        send(state='failed', error='A síntese Qwen local falhou. Confira os arquivos da voz e tente uma frase curta.')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
