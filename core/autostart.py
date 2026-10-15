import os
import sys
import winreg
import subprocess
from pathlib import Path
from core.config import config

class AutostartService:
    def __init__(self):
        self.app_name = config.AUTOSTART_NAME
        self.startup_dir = Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"))
        self.vbs_path = config.BASE_DIR / "start_jarvis.vbs"
        self.bat_path = config.BASE_DIR / "start_jarvis.bat"
        self.reg_key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def is_enabled(self) -> bool:
        """Checks if JARVIS is registered to launch at Windows startup."""
        # Check startup folder for shortcut or batch
        if (self.startup_dir / f"{self.app_name}.lnk").exists():
            return True
        if (self.startup_dir / f"{self.app_name}.vbs").exists():
            return True
            
        # Check Windows registry
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.reg_key_path, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, self.app_name)
                return bool(val)
        except FileNotFoundError:
            return False
        except Exception:
            return False

    def enable(self) -> tuple[bool, str]:
        """Enables startup on Windows boot via VBS script in Startup folder and Registry."""
        try:
            # 1. Ensure start_jarvis.vbs and start_jarvis.bat exist
            self._ensure_launcher_scripts()

            # 2. Copy/Create shortcut in Startup folder using PowerShell
            ps_cmd = (
                f"$WshShell = New-Object -comObject WScript.Shell; "
                f"$Shortcut = $WshShell.CreateShortcut('{self.startup_dir / f'{self.app_name}.lnk'}'); "
                f"$Shortcut.TargetPath = '{self.vbs_path}'; "
                f"$Shortcut.WorkingDirectory = '{config.BASE_DIR}'; "
                f"$Shortcut.Description = 'JARVIS Personal AI Assistant'; "
                f"$Shortcut.Save()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True, capture_output=True)

            # 3. Also add to Registry for redundancy
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.reg_key_path, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, self.app_name, 0, winreg.REG_SZ, f'wscript.exe "{self.vbs_path}"')

            # 4. Create Desktop shortcut
            self.create_desktop_shortcut()

            return True, "Inicialização automática ativada. O Jarvis iniciará sempre ao ligar o computador."
        except Exception as e:
            return False, f"Falha ao configurar inicialização automática: {e}"

    def create_desktop_shortcut(self):
        """Creates a shortcut on the user's Desktop."""
        try:
            desktop = Path.home() / "Desktop"
            ps_cmd = (
                f"$W = New-Object -comObject WScript.Shell; "
                f"$S = $W.CreateShortcut('{desktop / 'JARVIS.lnk'}'); "
                f"$S.TargetPath = '{self.bat_path}'; "
                f"$S.WorkingDirectory = '{config.BASE_DIR}'; "
                f"$S.Description = 'JARVIS AI Assistant'; "
                f"$S.Save()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True, capture_output=True)
        except Exception:
            pass

    def disable(self) -> tuple[bool, str]:
        """Disables Windows boot startup."""
        try:
            # Remove from startup folder
            lnk_path = self.startup_dir / f"{self.app_name}.lnk"
            if lnk_path.exists():
                lnk_path.unlink()

            vbs_startup = self.startup_dir / f"{self.app_name}.vbs"
            if vbs_startup.exists():
                vbs_startup.unlink()

            # Remove from registry
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.reg_key_path, 0, winreg.KEY_WRITE) as key:
                    winreg.DeleteValue(key, self.app_name)
            except FileNotFoundError:
                pass

            return True, "Inicialização automática desativada."
        except Exception as e:
            return False, f"Falha ao desativar inicialização automática: {e}"

    def _ensure_launcher_scripts(self):
        """Creates start_jarvis.bat and silent start_jarvis.vbs if not present."""
        python_exe = sys.executable
        runner_py = config.BASE_DIR / "run_jarvis.py"

        # .bat content
        bat_content = (
            f"@echo off\r\n"
            f"cd /d \"{config.BASE_DIR}\"\r\n"
            f"\"{python_exe}\" \"{runner_py}\"\r\n"
        )
        with open(self.bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)

        # .vbs content for silent launch without black console window
        vbs_content = (
            f"Set WshShell = CreateObject(\"WScript.Shell\")\r\n"
            f"WshShell.CurrentDirectory = \"{config.BASE_DIR}\"\r\n"
            f"WshShell.Run \"\"\"{python_exe}\"\" \"\"{runner_py}\"\"\", 0, False\r\n"
        )
        with open(self.vbs_path, "w", encoding="utf-8") as f:
            f.write(vbs_content)

autostart_service = AutostartService()
