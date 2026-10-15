"""Ask only this local JARVIS to shut down; never kill processes by wildcard."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import httpx
from core.config import config
try:
    with httpx.Client(base_url=f'http://127.0.0.1:{config.PORT}',timeout=15) as client:
        client.get('/').raise_for_status()
        client.post('/api/shutdown').raise_for_status()
    print('Encerramento solicitado ao JARVIS.')
except httpx.ConnectError:
    print('JARVIS não está em execução nesta porta.')
