"""Graceful stop, including waiting for the port before a subsequent start."""
import sys
import time
import socket
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import httpx

def stop_server(port,timeout=40):
    with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=20,trust_env=False) as client:
        try:
            health=client.get('/health');health.raise_for_status()
        except httpx.ConnectError:return False
        if health.json().get('engine')!='Hermes AIAgent':
            raise RuntimeError('A porta pertence a outro serviço. Nenhum processo foi encerrado.')
        client.get('/').raise_for_status()
        client.post('/api/shutdown').raise_for_status()
    # Release the HTTP keep-alive before awaiting shutdown. Test the listening
    # port itself; an old HTTP connection is not evidence of a running server.
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        with socket.socket() as probe:
            probe.settimeout(.5)
            if probe.connect_ex(('127.0.0.1',port))!=0:return True
        time.sleep(.2)
    raise TimeoutError('O JARVIS ainda está encerrando. Aguarde a liberação da porta antes de iniciar outra instância.')


def main():
    from core.config import config
    try:
        stopped=stop_server(config.PORT)
        print('JARVIS encerrado; a porta está liberada para iniciar novamente.' if stopped else 'JARVIS já está encerrado nesta porta.')
        return 0
    except (httpx.HTTPError,ValueError,RuntimeError,TimeoutError) as exc:
        print('Não foi possível concluir o encerramento: '+str(exc),file=sys.stderr)
        return 1


if __name__=='__main__':sys.exit(main())
