"""Single foreground server, explicit browser launch, graceful stop."""
import argparse
import asyncio
import socket
import webbrowser
import uvicorn
from core.config import config
from core.safety import atomic_write
import server

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser',action='store_true')
    args = parser.parse_args()
    if config.HOST not in ('127.0.0.1','localhost'):
        raise SystemExit('JARVIS permite somente acesso local. Use HOST=127.0.0.1.')
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',config.PORT))==0:
            raise SystemExit(f'A porta {config.PORT} já está ocupada. Nenhuma segunda instância foi iniciada.')
    import os
    atomic_write(config.DATA_DIR/'server.pid',str(os.getpid()))
    uvserver = uvicorn.Server(uvicorn.Config(server.app,host=config.HOST,port=config.PORT,log_level='warning'))
    server.shutdown_callback = lambda:setattr(uvserver,'should_exit',True)
    async def run():
        async def open_browser():
            while not uvserver.started and not uvserver.should_exit:
                await asyncio.sleep(.1)
            if uvserver.started and not args.no_browser:
                webbrowser.open(f'http://127.0.0.1:{config.PORT}')
        opening = asyncio.create_task(open_browser())
        try:
            print(f'JARVIS / Hermes: http://127.0.0.1:{config.PORT}')
            await uvserver.serve()
        finally:
            opening.cancel()
            (config.DATA_DIR/'server.pid').unlink(missing_ok=True)
    asyncio.run(run())

if __name__=='__main__':
    main()
