"""Windows conveniences with explicit targets; never interprets model text as shell."""
import os
from pathlib import Path
import shutil
import subprocess
import time
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

    def __init__(self):
        self._catalog=None
        self._catalog_stamp=0

    def app_catalog(self):
        """Names from installed Windows app registrations, not executable text from a model."""
        if self._catalog is not None and time.monotonic()-self._catalog_stamp<300:
            return self._catalog
        result={}
        if os.name=='nt':
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
                for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
                    try:
                        with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths',0,winreg.KEY_READ|view) as key:
                            for index in range(winreg.QueryInfoKey(key)[0]):
                                name=winreg.EnumKey(key,index)
                                try:
                                    with winreg.OpenKey(key,name) as entry:
                                        target=Path(os.path.expandvars(winreg.QueryValue(entry,None).strip('"')))
                                        if target.is_file() and target.suffix.lower()=='.exe': result[target.stem.casefold()]=str(target)
                                except OSError: continue
                    except OSError: continue
            import pythoncom
            from win32com.client import Dispatch
            pythoncom.CoInitialize()
            try:
                shell=Dispatch('WScript.Shell')
                for key in ('APPDATA','PROGRAMDATA'):
                    folder=Path(os.environ.get(key,''))/'Microsoft/Windows/Start Menu/Programs'
                    if not folder.is_dir(): continue
                    for link in list(folder.rglob('*.lnk'))[:250]:
                        if any(word in link.stem.casefold() for word in ('uninstall','desinstal','remove','setup','install','update','repair')): continue
                        try:
                            target=Path(shell.CreateShortcut(str(link)).TargetPath)
                            if target.is_file() and target.suffix.lower()=='.exe':
                                result.setdefault(link.stem.casefold(),str(link))
                        except Exception: continue
            finally:
                shell=None
                pythoncom.CoUninitialize()
        self._catalog=result; self._catalog_stamp=time.monotonic()
        return result

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
        elif name in self.app_catalog() and name not in self.APPS:
            target=self.app_catalog()[name]
            if Path(target).suffix.lower()=='.lnk': os.startfile(target)
            else: subprocess.Popen([target],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        elif name in self.APPS:
            app=self.APPS[name]
            found=shutil.which(app)
            if not found and app in ('chrome.exe','msedge.exe'):
                relative='Google/Chrome/Application/chrome.exe' if app=='chrome.exe' else 'Microsoft/Edge/Application/msedge.exe'
                found=next((str(Path(os.environ.get(key,''))/relative) for key in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA') if (Path(os.environ.get(key,''))/relative).is_file()),None)
            if not found:
                registered=self.app_catalog().get(name) or self.app_catalog().get(Path(app).stem.casefold())
                if registered:
                    if Path(registered).suffix.lower()=='.lnk':
                        os.startfile(registered)
                        return True,'Solicitação de abertura enviada ao Windows: '+name
                    found=registered
                else: raise FileNotFoundError('Aplicativo não localizado: '+name)
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

    def take_screenshot(self):
        import pyautogui
        path=config.WORKSPACE_ROOTS[0]/'Screenshots'/datetime.now().strftime('%Y%m%d-%H%M%S-%f.png')
        path.parent.mkdir(parents=True,exist_ok=True)
        image=pyautogui.screenshot();image.save(path)
        if not path.is_file() or path.stat().st_size==0:
            raise IOError('Captura não confirmada.')
        return {'verified':True,'path':str(path),'bytes':path.stat().st_size}

automation_service=AutomationService()
