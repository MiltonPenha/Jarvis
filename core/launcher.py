"""Desktop launcher helpers, without importing the assistant or audio services."""
import json
import os
from pathlib import Path
import subprocess
from urllib.request import Request, ProxyHandler, build_opener
import webbrowser


def is_jarvis_running(port):
    try:
        request = Request(f'http://127.0.0.1:{port}/health')
        with build_opener(ProxyHandler({})).open(request, timeout=2) as response:
            health = json.loads(response.read(2048))
        return health.get('status') == 'online' and health.get('engine') == 'Hermes AIAgent'
    except (OSError, ValueError):
        return False


def open_hud(port):
    """Open an app window using an installed browser, or the system browser."""
    url = f'http://127.0.0.1:{port}'
    candidates = [
        Path(os.environ.get('PROGRAMFILES', r'C:\Program Files')) / 'Google/Chrome/Application/chrome.exe',
        Path(os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')) / 'Google/Chrome/Application/chrome.exe',
        Path(os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
        Path(os.environ.get('PROGRAMFILES', r'C:\Program Files')) / 'Microsoft/Edge/Application/msedge.exe',
    ]
    for executable in candidates:
        if executable.is_file():
            try:
                subprocess.Popen([str(executable), f'--app={url}', '--window-size=1300,900'])
                return True
            except OSError:
                continue
    if webbrowser.open(url, new=1):
        return True
    raise RuntimeError(f'Não foi possível abrir uma janela. Acesse {url} no navegador.')
