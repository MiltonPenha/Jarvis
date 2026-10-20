"""Explicit download into JARVIS's private model directory; no GPU or other Ollama instance."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx
from core.local_model import local_model, MODEL, BASE_URL

def main():
    try:
        local_model.start()
        with httpx.Client(base_url=BASE_URL, trust_env=False, timeout=600) as client:
            if not local_model.prepared():
                last = -1
                with client.stream('POST', '/api/pull', json={'model':MODEL}) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        data = json.loads(line)
                        if data.get('error'): raise RuntimeError(data['error'])
                        percent = int(data.get('completed',0)*100/max(1,data.get('total',1)))
                        if percent//10 != last:
                            print(data.get('status'), percent, flush=True); last=percent//10
            info = client.post('/api/show', json={'model':MODEL}); info.raise_for_status()
            print(json.dumps({'model':MODEL, 'prepared':local_model.prepared(), 'details':info.json().get('details')}, ensure_ascii=False))
    finally:
        local_model.stop()

if __name__=='__main__': main()
