"""Supported connection to the user's Chrome. Profile metadata only, no cookies.

Chrome 144+ can authorize remote control at runtime. Playwright 1.64 resolves
the public channel endpoint 'chrome'; no remote-debugging launch switches.
"""
import json
import os
from pathlib import Path
import re
import subprocess
from core.config import config
from core.safety import atomic_write
from urllib.parse import urlparse

AUTH_URL='chrome://inspect/#remote-debugging'


def profile_catalog():
    root=Path(os.getenv('LOCALAPPDATA',''))/'Google/Chrome/User Data'
    path=root/'Local State'
    try:data=json.loads(path.read_text(encoding='utf-8')).get('profile',{})
    except (OSError,ValueError):data={}
    # Do not return account emails, GAIA IDs, credentials or other profile data.
    rows=[{'directory':name,'name':row.get('name') or name} for name,row in data.get('info_cache',{}).items()
        if re.fullmatch(r'Default|Profile \d+',name)]
    return {'profiles':rows,'last_used':data.get('last_used','Default'),'root':root}


def browser_settings():
    catalog=profile_catalog()
    value={'mode':'chrome','profile':catalog['last_used'],'endpoint':'chrome','require_youtube_login':True}
    path=config.DATA_DIR/'browser-settings.json'
    if path.exists():value.update(json.loads(path.read_text(encoding='utf-8')))
    return value


def save_browser_settings(changes):
    if set(changes)-{'mode','profile','endpoint'}:raise ValueError('Configuração de navegador desconhecida.')
    value={**browser_settings(),**changes}
    if value['mode'] not in ('chrome','isolated'):raise ValueError('Modo de navegador inválido.')
    profiles={row['directory'] for row in profile_catalog()['profiles']}
    if value['profile'] not in profiles:raise ValueError('Selecione um perfil Chrome existente.')
    if value['endpoint']!='chrome':
        parsed=urlparse(value['endpoint'])
        if parsed.scheme not in ('http','ws') or parsed.hostname not in ('127.0.0.1','localhost','::1') or parsed.username or parsed.password or not parsed.port:
            raise ValueError('A conexão Chrome deve apontar para um endereço local autorizado.')
    atomic_write(config.DATA_DIR/'browser-settings.json',json.dumps(value,ensure_ascii=False,indent=2))
    return value


def chrome_executable():
    for name in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
        path=Path(os.getenv(name,''))/'Google/Chrome/Application/chrome.exe'
        if path.is_file():return path
    raise RuntimeError('Google Chrome não encontrado neste computador.')


def open_authorization():
    # Normal launch reuses the existing profile/process. Never passes user-data-dir,
    # remote-debugging flags or options that disable browser protections.
    profile=browser_settings()['profile']
    subprocess.Popen([str(chrome_executable()),'--profile-directory='+profile,AUTH_URL],
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return {'stage':'connection_authorization','verified':False,'authorization_required':True,
        'message':'Senhor, no Chrome aberto, habilite “Permitir depuração remota para esta instância do navegador”. Depois clique em Conectar no JARVIS e aceite a solicitação do próprio Chrome.'}


def connection_status():
    catalog=profile_catalog();selected=browser_settings()
    active=catalog['root']/'DevToolsActivePort'
    endpoint=selected['endpoint']
    # Runtime-authorized Chrome exposes WebSocket CDP without /json/version.
    # Resolve only the configured local port, using Chrome's own published file.
    if endpoint!='chrome' and active.is_file():
        try:
            lines=active.read_text(encoding='utf-8').splitlines()
            port=int(lines[0])
            parsed=urlparse(endpoint)
            if parsed.scheme=='http' and parsed.port==port:
                path=lines[1] if len(lines)>1 and re.fullmatch(r'/devtools/browser/[a-zA-Z0-9-]+',lines[1]) else '/devtools/browser'
                endpoint=f'ws://{parsed.hostname}:{port}{path}'
        except (OSError,ValueError,IndexError):pass
    return {**selected,'resolved_endpoint':endpoint,'profiles':catalog['profiles'],'authorization_available':active.is_file(),
        'authorization_url':AUTH_URL,'connection':'Playwright CDP channel chrome, no_defaults=True'}
