"""Single foreground server, explicit browser launch, graceful stop."""
import argparse
import asyncio
import socket
import uvicorn
from core.config import config
from core.safety import atomic_write
from core.launcher import is_jarvis_running,open_hud

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser',action='store_true')
    args = parser.parse_args()
    if config.HOST not in ('127.0.0.1','localhost'):
        raise SystemExit('JARVIS permite somente acesso local. Use HOST=127.0.0.1.')
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',config.PORT))==0:
            if is_jarvis_running(config.PORT):
                if not args.no_browser:
                    open_hud(config.PORT)
                print(f'JARVIS já está ativo: http://127.0.0.1:{config.PORT}')
                return
            raise SystemExit(f'A porta {config.PORT} já está ocupada. Nenhuma segunda instância foi iniciada.')
    import server
    import os
    atomic_write(config.DATA_DIR/'server.pid',str(os.getpid()))
    uvserver = uvicorn.Server(uvicorn.Config(server.app,host=config.HOST,port=config.PORT,log_level='warning'))
    server.shutdown_callback = lambda:setattr(uvserver,'should_exit',True)
    async def run():
        async def open_browser():
            while not uvserver.started and not uvserver.should_exit:
                await asyncio.sleep(.1)
            if uvserver.started and not args.no_browser:
                await asyncio.to_thread(open_hud,config.PORT)
        opening = asyncio.create_task(open_browser())
        try:
            print(f'JARVIS / Hermes: http://127.0.0.1:{config.PORT}')
            await uvserver.serve()
        finally:
            opening.cancel()
            marker=config.DATA_DIR/'server.pid'
            try:
                if marker.read_text(encoding='utf-8').strip()==str(os.getpid()):marker.unlink(missing_ok=True)
            except OSError:pass
    asyncio.run(run())

if __name__=='__main__':
    main()
