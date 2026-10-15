"""A single Windows Run registration; no registration or launcher writes at import."""
import os
import sys
from pathlib import Path
try:
    import winreg
except ImportError:
    winreg=None
from core.config import config

class AutostartService:
    def __init__(self):
        self.reg_key_path=r'Software\Microsoft\Windows\CurrentVersion\Run'
        self.startup_dir=Path(os.path.expandvars(r'%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup'))

    def is_enabled(self):
        if winreg is None:return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.reg_key_path,0,winreg.KEY_READ) as key:
                value,_=winreg.QueryValueEx(key,config.AUTOSTART_NAME)
                return bool(value)
        except OSError:
            return any((self.startup_dir/(config.AUTOSTART_NAME+suffix)).exists() for suffix in ('.lnk','.vbs'))

    def enable(self):
        if winreg is None:return False,'Inicialização automática disponível apenas no Windows.'
        try:
            python=config.BASE_DIR/'.venv/Scripts/pythonw.exe'
            if not python.exists():
                python=Path(sys.executable).with_name('pythonw.exe')
            if not python.exists():raise FileNotFoundError('pythonw.exe ausente')
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,self.reg_key_path) as key:
                winreg.SetValueEx(key,config.AUTOSTART_NAME,0,winreg.REG_SZ,f'"{python}" "{config.BASE_DIR / "run_jarvis.py"}"')
            # Clean the old redundant registration only after the new one succeeds.
            for suffix in ('.lnk','.vbs'):
                (self.startup_dir/(config.AUTOSTART_NAME+suffix)).unlink(missing_ok=True)
            return self.is_enabled(),'Inicialização automática registrada em um único local.'
        except OSError as exc:return False,'Não foi possível registrar: '+type(exc).__name__

    def disable(self):
        if winreg is None:return False,'Windows indisponível.'
        try:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.reg_key_path,0,winreg.KEY_WRITE) as key:
                    winreg.DeleteValue(key,config.AUTOSTART_NAME)
            except FileNotFoundError:pass
            for suffix in ('.lnk','.vbs'):
                (self.startup_dir/(config.AUTOSTART_NAME+suffix)).unlink(missing_ok=True)
            return not self.is_enabled(),'Inicialização automática desativada.'
        except OSError as exc:return False,'Não foi possível desativar: '+type(exc).__name__

autostart_service=AutostartService()
