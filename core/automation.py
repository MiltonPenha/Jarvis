import os
import sys
import ctypes
import subprocess
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

import pyautogui
from ddgs import DDGS

from core.config import config

class AutomationService:
    def __init__(self):
        self.user_32 = ctypes.windll.user32
        self.VK_VOLUME_MUTE = 0xAD
        self.VK_VOLUME_DOWN = 0xAE
        self.VK_VOLUME_UP = 0xAF

        # Locate browser binaries for guaranteed tab spawning
        self.chrome_exe = None
        self.edge_exe = None
        for p in [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ]:
            if Path(p).exists():
                self.chrome_exe = p
                break

        for p in [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
        ]:
            if Path(p).exists():
                self.edge_exe = p
                break

        # Known common Windows application shortcuts and commands
        self.common_apps = {
            "youtube": "https://www.youtube.com",
            "google chrome": "chrome",
            "chrome": "chrome",
            "navegador": "chrome",
            "google": "https://www.google.com",
            "whatsapp": "https://web.whatsapp.com",
            "discord": "discord",
            "spotify": "spotify",
            "steam": "steam",
            "vscode": "code",
            "vs code": "code",
            "visual studio code": "code",
            "bloco de notas": "notepad",
            "notepad": "notepad",
            "calculadora": "calc",
            "gerenciador de tarefas": "taskmgr",
            "configurações": "ms-settings:",
            "terminal": "wt",
            "powershell": "powershell",
            "cmd": "cmd",
            "prompt de comando": "cmd",
            "explorador de arquivos": "explorer",
            "meus arquivos": "explorer",
            "downloads": str(Path.home() / "Downloads"),
            "documentos": str(Path.home() / "Documents"),
            "área de trabalho": str(Path.home() / "Desktop"),
            "desktop": str(Path.home() / "Desktop"),
        }

    def open_url(self, url: str) -> bool:
        """
        Reliably launches a URL in a new browser window/tab.
        Bypasses limitations of Python's webbrowser module when running inside Chrome App Mode.
        """
        clean_url = url.strip()
        if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
            clean_url = f"https://{clean_url}"

        # 1. Direct Chrome spawn
        if self.chrome_exe:
            try:
                subprocess.Popen([self.chrome_exe, clean_url])
                return True
            except Exception:
                pass

        # 2. Direct Edge spawn
        if self.edge_exe:
            try:
                subprocess.Popen([self.edge_exe, clean_url])
                return True
            except Exception:
                pass

        # 3. Native Windows ShellExecute
        try:
            os.startfile(clean_url)
            return True
        except Exception:
            pass

        # 4. Windows CMD start
        try:
            subprocess.Popen(f'start "" "{clean_url}"', shell=True)
            return True
        except Exception:
            pass

        return False

    def open_target(self, target: str) -> tuple[bool, str]:
        """
        Intelligently opens a program, file, URL, or Windows tool.
        """
        clean_target = target.lower().strip()

        # 1. Check if it's already a direct URL
        if clean_target.startswith("http://") or clean_target.startswith("https://"):
            self.open_url(clean_target)
            return True, f"Abrindo {target} no seu navegador."

        # 2. Check known apps & shortcuts
        if clean_target in self.common_apps:
            cmd = self.common_apps[clean_target]
            if cmd.startswith("http://") or cmd.startswith("https://"):
                self.open_url(cmd)
                return True, f"Abrindo {target} no seu navegador."
            elif cmd.startswith("ms-settings:"):
                subprocess.Popen(["cmd", "/c", "start", cmd], shell=True)
                return True, f"Abrindo configurações do Windows."
            elif Path(cmd).exists():
                os.startfile(cmd)
                return True, f"Abrindo a pasta {target}."
            else:
                try:
                    subprocess.Popen(cmd, shell=True)
                    return True, f"Iniciando {target}."
                except Exception as e:
                    return False, f"Falha ao abrir {target}: {e}"

        # 3. Check if target is a web domain
        if any(clean_target.endswith(ext) for ext in [".com", ".com.br", ".org", ".net", ".io", ".gov", ".edu"]):
            self.open_url(clean_target)
            return True, f"Acessando {clean_target}."

        # 4. Check if target is a file or directory path
        target_path = Path(clean_target)
        if target_path.exists():
            os.startfile(target_path)
            return True, f"Abrindo arquivo {target_path.name}."

        # 5. Search user's Desktop, Documents, Downloads for matching filename
        search_dirs = [Path.home() / "Desktop", Path.home() / "Documents", Path.home() / "Downloads"]
        for sdir in search_dirs:
            if not sdir.exists():
                continue
            for item in sdir.glob("*"):
                if clean_target in item.name.lower():
                    os.startfile(item)
                    return True, f"Localizei e abri {item.name}."

        # 6. Fallback: try Windows subprocess
        try:
            subprocess.Popen(clean_target, shell=True)
            return True, f"Iniciando {clean_target}."
        except Exception:
            pass

        return False, f"Não encontrei o aplicativo ou arquivo '{target}', senhor."

    def search_google(self, query: str) -> str:
        """Opens Google search in the browser."""
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        self.open_url(url)
        return f"Realizando busca por '{query}' no Google."

    def web_search(self, query: str, max_results: int = 4) -> List[Dict[str, str]]:
        """
        Executes web search without API keys and returns structured results.
        """
        try:
            results = list(DDGS().text(query, max_results=max_results))
            return [
                {
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", "")
                }
                for r in results
            ]
        except Exception as e:
            print(f"Erro na pesquisa web: {e}")
            return []

    def volume_up(self, steps: int = 5):
        """Increases Windows master volume."""
        for _ in range(steps):
            self.user_32.keybd_event(self.VK_VOLUME_UP, 0, 0, 0)
            self.user_32.keybd_event(self.VK_VOLUME_UP, 0, 2, 0)

    def volume_down(self, steps: int = 5):
        """Decreases Windows master volume."""
        for _ in range(steps):
            self.user_32.keybd_event(self.VK_VOLUME_DOWN, 0, 0, 0)
            self.user_32.keybd_event(self.VK_VOLUME_DOWN, 0, 2, 0)

    def volume_mute(self):
        """Toggles Windows mute."""
        self.user_32.keybd_event(self.VK_VOLUME_MUTE, 0, 0, 0)
        self.user_32.keybd_event(self.VK_VOLUME_MUTE, 0, 2, 0)

    def take_screenshot(self) -> tuple[bool, str]:
        """Takes a desktop screenshot and saves to pictures directory."""
        try:
            pictures_dir = Path.home() / "Pictures" / "JARVIS"
            pictures_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = pictures_dir / f"screenshot_{timestamp}.png"
            
            screenshot = pyautogui.screenshot()
            screenshot.save(filepath)
            
            # Open screenshot
            os.startfile(filepath)
            return True, f"Captura de tela salva com sucesso em {filepath.name}."
        except Exception as e:
            return False, f"Falha ao capturar a tela: {e}"

    def minimize_all_windows(self):
        """Minimizes all open windows using Win+D shortcut."""
        pyautogui.hotkey('win', 'd')

    def lock_workstation(self):
        """Locks the Windows computer."""
        ctypes.windll.user32.LockWorkStation()

automation_service = AutomationService()
