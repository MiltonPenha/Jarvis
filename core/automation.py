"""Windows conveniences with explicit targets; never interprets model text as shell."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlparse
from datetime import datetime
from core.config import config

class AutomationService:
    APPS = {'chrome':'chrome.exe','google chrome':'chrome.exe','edge':'msedge.exe',
            'notepad':'notepad.exe','bloco de notas':'notepad.exe','calculadora':'calc.exe',
            'code':'code.cmd','vscode':'code.cmd','spotify':'spotify.exe','discord':'discord.exe',
            'explorer':'explorer.exe'}
    SITES = {'youtube':'https://www.youtube.com','google':'https://www.google.com',
             'github':'https://github.com','whatsapp':'https://web.whatsapp.com'}

    def open_url(self,url):
        parsed=urlparse(url)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('Somente URLs HTTP/HTTPS sem credenciais.')
        os.startfile(url)
        return True

    def open_target(self,target):
        target=target.strip()
        name=target.casefold()
        if name in self.SITES:
            self.open_url(self.SITES[name])
        elif target.startswith(('http://','https://')):
            self.open_url(target)
        elif name in ('obsidian','cofre'):
            os.startfile(config.OBSIDIAN_VAULT_PATH)
        elif name in self.APPS:
            app=self.APPS[name]
            found=shutil.which(app)
            if not found and app in ('chrome.exe','msedge.exe'):
                relative='Google/Chrome/Application/chrome.exe' if app=='chrome.exe' else 'Microsoft/Edge/Application/msedge.exe'
                found=next((str(Path(os.environ.get(key,''))/relative) for key in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA') if (Path(os.environ.get(key,''))/relative).is_file()),None)
            if not found:
                raise FileNotFoundError('Aplicativo não localizado: '+name)
            if Path(found).suffix.lower() in ('.cmd','.bat'):
                # Windows' shell treatment of batch files is not an accepted tool path.
                code_exe=Path(found).parent.parent/'Code.exe'
                if not code_exe.is_file():
                    raise ValueError('Configure um executável nativo para este aplicativo.')
                found=str(code_exe)
            subprocess.Popen([found],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        else:
            path=Path(target).resolve()
            root=next((root for root in config.WORKSPACE_ROOTS if path==root or path.is_relative_to(root)),None)
            if root is None or not path.exists():
                raise PermissionError('Destino não reconhecido ou fora dos diretórios autorizados.')
            if path!=root:
                from core.safety import checked_path
                checked_path(root,path.relative_to(root))
            os.startfile(str(path))
        return True,'Solicitação de abertura enviada ao Windows: '+target

    def media_key(self,key):
        codes={'play_pause':0xB3,'next':0xB0,'previous':0xB1,'stop':0xB2,'volume_up':0xAF,'volume_down':0xAE,'mute':0xAD}
        if key not in codes:
            raise ValueError('Controle de mídia inválido.')
        user=ctypes.windll.user32
        user.keybd_event(codes[key],0,0,0);user.keybd_event(codes[key],0,2,0)
        return {'verified':True,'command_sent':key,'note':'Evento enviado ao Windows; estado do player não é observável.'}

    def take_screenshot(self):
        import pyautogui
        path=config.WORKSPACE_ROOTS[0]/'Screenshots'/datetime.now().strftime('%Y%m%d-%H%M%S-%f.png')
        path.parent.mkdir(parents=True,exist_ok=True)
        image=pyautogui.screenshot();image.save(path)
        if not path.is_file() or path.stat().st_size==0:
            raise IOError('Captura não confirmada.')
        return {'verified':True,'path':str(path),'bytes':path.stat().st_size}

automation_service=AutomationService()
