import re
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from core.config import config
from core.system_monitor import system_monitor
from core.automation import automation_service
from core.music_player import music_player
from core.autostart import autostart_service
from core.llm_brain import llm_brain

class CommandDispatcher:
    def __init__(self):
        self.commands_file = config.COMMANDS_FILE
        self.custom_commands = self.load_custom_commands()
        
        # Direct keyword targets
        self.known_targets = {
            "youtube": "https://www.youtube.com",
            "google chrome": "chrome",
            "chrome": "chrome",
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
            "prompt": "cmd",
            "explorador de arquivos": "explorer",
            "downloads": str(Path.home() / "Downloads"),
            "documentos": str(Path.home() / "Documents"),
            "área de trabalho": str(Path.home() / "Desktop"),
            "desktop": str(Path.home() / "Desktop"),
        }

    def load_custom_commands(self) -> list:
        if self.commands_file.exists():
            try:
                with open(self.commands_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("custom_commands", [])
            except Exception as e:
                print(f"Erro ao ler commands.json: {e}")
        return []

    def reload_custom_commands(self):
        self.custom_commands = self.load_custom_commands()

    def clean_text(self, text: str) -> str:
        """Normalizes user speech text, removing punctuation and wake words."""
        cleaned = text.lower().strip()
        cleaned = re.sub(r"[?!.,;:]+$", "", cleaned)
        
        # Remove wake words from anywhere in the beginning
        for wake in sorted(config.WAKE_WORDS, key=len, reverse=True):
            cleaned = re.sub(rf"\b{re.escape(wake)}\b", "", cleaned).strip()
            
        return cleaned.strip()

    def execute_command(self, raw_text: str) -> dict:
        """
        Parses user text with natural language semantic understanding.
        Resolves intents anywhere in the sentence, handling polite conversational phrases.
        """
        text = raw_text.lower().strip()
        cleaned = self.clean_text(raw_text)

        # 1. Custom User-Defined Commands from commands.json
        for cmd in self.custom_commands:
            trigger = cmd.get("trigger", "").lower().strip()
            if trigger and trigger in text:
                action_type = cmd.get("action_type")
                speech = cmd.get("speech_response", f"Comando '{trigger}' executado.")
                if action_type in ["open_url", "open_app", "open_folder"]:
                    target = cmd.get("target")
                    if target:
                        automation_service.open_target(target)
                elif action_type == "open_multiple":
                    targets = cmd.get("targets", [])
                    for t in targets:
                        automation_service.open_target(t)
                return {
                    "type": "custom_macro",
                    "command": raw_text,
                    "response_speech": speech,
                    "display_text": speech
                }

        # List of opening action verbs
        open_verbs = ["abrir", "abre", "abra", "iniciar", "inicie", "acessar", "acessa", "acesse", "carregar", "coloque", "coloca"]
        has_open_intent = any(v in text for v in open_verbs)

        # 2. SEMANTIC APP / WEBSITE OPENING (Matches anywhere in sentence!)
        if has_open_intent:
            # Check for known targets first
            for target_name, target_action in self.known_targets.items():
                if target_name in text:
                    automation_service.open_target(target_action)
                    speech = f"Com certeza, {config.USER_NAME}. Abrindo {target_name.capitalize()} para você."
                    return {
                        "type": "open",
                        "command": raw_text,
                        "response_speech": speech,
                        "display_text": speech
                    }

            # Generic open matcher (extracts whatever follows open verb)
            open_extract = re.search(r"(?:abrir|abre|abra|iniciar|inicie|acessar|acesse)\s+(?:o\s+|a\s+|o\s+site\s+|o\s+app\s+|o\s+programa\s+|a\s+página\s+)?([a-zA-Z0-9_\-\.\s]+?)(?:\s+para\s+mim|\s+pra\s+mim|\s+por\s+favor|\s+aí)?$", cleaned)
            if open_extract:
                target_str = open_extract.group(1).strip()
                if target_str:
                    success, speech = automation_service.open_target(target_str)
                    return {
                        "type": "open",
                        "command": raw_text,
                        "response_speech": speech,
                        "display_text": speech
                    }

        # 3. DIRECT GOOGLE SEARCH
        if any(p in text for p in ["pesquisar no google", "pesquisa no google", "busca no google", "buscar no google", "pesquise no google"]):
            query_match = re.search(r"(?:pesquisar|pesquisa|pesquise|buscar|busca|busque)\s+no\s+google\s+(?:por\s+|sobre\s+)?(.+)", text)
            if query_match:
                query = query_match.group(1).replace("para mim", "").replace("por favor", "").strip()
                speech = automation_service.search_google(query)
                return {"type": "google_search", "command": raw_text, "response_speech": speech, "display_text": speech}

        # 4. MUSIC PLAYBACK (Matches anywhere in sentence)
        music_verbs = ["tocar", "toque", "toca", "coloque", "coloca", "bota", "ouvir", "reproduzir"]
        if any(v in text for v in music_verbs) and not any(p in text for p in ["pesquisa", "google", "como está"]):
            music_match = re.search(r"(?:tocar|toque|toca|coloque|coloca|bota|ouvir|reproduzir)\s+(?:a\s+música\s+|música\s+|som\s+)?(.+)", text)
            if music_match:
                song = music_match.group(1)
                for filler in ["no youtube", "no spotify", "para mim", "pra mim", "por favor", "aí"]:
                    song = song.replace(filler, "")
                song = song.strip()
                if song:
                    if "spotify" in text:
                        success, speech = music_player.play_spotify(song)
                    else:
                        success, speech = music_player.play_music(song)
                    return {"type": "music_play", "command": raw_text, "response_speech": speech, "display_text": speech}

        # 5. MEDIA CONTROLS
        if any(p in text for p in ["pausar música", "pausar som", "pausar áudio", "continuar música", "despausar", "pausa o som", "pausa a música"]):
            music_player.toggle_play_pause()
            speech = f"Controle de mídia executado, {config.USER_NAME}."
            return {"type": "music_control", "command": raw_text, "response_speech": speech, "display_text": speech}

        if any(p in text for p in ["próxima música", "pular música", "trocar de música", "passar música"]):
            music_player.next_track()
            speech = f"Avançando para a próxima faixa."
            return {"type": "music_control", "command": raw_text, "response_speech": speech, "display_text": speech}

        # 6. SYSTEM STATUS / TELEMETRY
        if any(p in text for p in ["status do sistema", "como está o pc", "como está o computador", "relatório do sistema", "uso de memória", "uso de processador", "status do pc"]):
            speech = system_monitor.get_status_speech()
            metrics = system_monitor.get_metrics()
            return {
                "type": "system_status",
                "command": raw_text,
                "response_speech": speech,
                "display_text": speech,
                "data": metrics
            }

        # 7. TIME & DATE
        if any(p in text for p in ["que horas são", "qual é a hora", "me diga as horas", "horas agora"]):
            now_str = datetime.now().strftime("%H horas e %M minutos")
            speech = f"Agora são {now_str}, {config.USER_NAME}."
            return {"type": "time", "command": raw_text, "response_speech": speech, "display_text": speech}

        if any(p in text for p in ["que dia é hoje", "qual a data de hoje", "data de hoje"]):
            meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
            now = datetime.now()
            speech = f"Hoje é dia {now.day} de {meses[now.month - 1]} de {now.year}."
            return {"type": "date", "command": raw_text, "response_speech": speech, "display_text": speech}

        # 8. VOLUME CONTROLS
        if any(p in text for p in ["aumentar volume", "aumente o volume", "aumenta o som", "mais alto", "sobe o volume"]):
            automation_service.volume_up(steps=6)
            speech = f"Volume aumentado, {config.USER_NAME}."
            return {"type": "volume", "command": raw_text, "response_speech": speech, "display_text": speech}

        if any(p in text for p in ["diminuir volume", "diminua o volume", "abaixar volume", "abaixe o volume", "mais baixo", "baixa o som"]):
            automation_service.volume_down(steps=6)
            speech = f"Volume reduzido, {config.USER_NAME}."
            return {"type": "volume", "command": raw_text, "response_speech": speech, "display_text": speech}

        if any(p in text for p in ["mutar som", "mutar áudio", "silenciar", "mudo"]):
            automation_service.volume_mute()
            speech = f"Áudio silenciado."
            return {"type": "volume", "command": raw_text, "response_speech": speech, "display_text": speech}

        # 9. SCREENSHOT / PRINT
        if any(p in text for p in ["tirar print", "captura de tela", "screenshot", "tira um print"]):
            success, speech = automation_service.take_screenshot()
            return {"type": "screenshot", "command": raw_text, "response_speech": speech, "display_text": speech}

        # 10. WINDOW / DESKTOP MANAGEMENT
        if any(p in text for p in ["minimizar tudo", "minimizar janelas", "mostrar área de trabalho", "mostrar desktop"]):
            automation_service.minimize_all_windows()
            speech = f"Minimizando janelas para o senhor."
            return {"type": "desktop", "command": raw_text, "response_speech": speech, "display_text": speech}

        if any(p in text for p in ["bloquear computador", "bloquear pc", "travar tela"]):
            speech = f"Bloqueando a estação de trabalho. Até logo, {config.USER_NAME}."
            automation_service.lock_workstation()
            return {"type": "security", "command": raw_text, "response_speech": speech, "display_text": speech}

        # 10.5 SHUTDOWN / CLOSE JARVIS
        shutdown_triggers = ["encerrar jarvis", "fechar jarvis", "desligar jarvis", "parar jarvis", "parar tudo", "sair do jarvis", "stop jarvis", "encerrar o jarvis", "fechar o jarvis", "desligar o jarvis"]
        if any(t in text for t in shutdown_triggers) or (cleaned in ["encerrar", "fechar", "sair", "desligar", "stop", "parar"]):
            speech = f"Encerrando todos os protocolos e finalizando o Jarvis. Até logo, {config.USER_NAME}."
            def _exit_later():
                import time, os
                time.sleep(3.5) # Wait for speech to finish
                os._exit(0)
            import threading
            threading.Thread(target=_exit_later, daemon=True).start()
            return {"type": "shutdown", "command": raw_text, "response_speech": speech, "display_text": speech}

        # 11. WINDOWS AUTOSTART ON BOOT
        if any(p in text for p in ["iniciar com o windows", "inicialização automática", "ligar junto com o pc"]):
            if "desativar" in text or "cancelar" in text or "remover" in text:
                _, speech = autostart_service.disable()
            else:
                _, speech = autostart_service.enable()
            return {"type": "autostart", "command": raw_text, "response_speech": speech, "display_text": speech}

        # 11.5 OBSIDIAN MEMORY COMMANDS
        if any(p in text for p in ["abrir obsidian", "abrir cofre de memória", "abrir cofre", "abrir pasta de memória", "mostrar memória"]):
            from core.memory_obsidian import obsidian_memory
            obsidian_memory.open_vault_folder()
            speech = f"Abrindo o cofre de memória do Obsidian, {config.USER_NAME}."
            return {"type": "memory", "command": raw_text, "response_speech": speech, "display_text": speech}

        task_match = re.search(r"(?:adicionar tarefa|adiciona tarefa|novo lembrete|criar lembrete|lembrete de|anotar tarefa)\s+(.+)", text)
        if task_match:
            from core.memory_obsidian import obsidian_memory
            task_desc = task_match.group(1).replace("para mim", "").replace("por favor", "").strip()
            speech = obsidian_memory.add_task(task_desc)
            return {"type": "memory_task", "command": raw_text, "response_speech": speech, "display_text": speech}

        note_match = re.search(r"(?:anote que|lembre que|lembrar que|guarde na memória que|salvar nota sobre|anotar que)\s+(.+)", text)
        if note_match:
            from core.memory_obsidian import obsidian_memory
            note_content = note_match.group(1).strip()
            speech = obsidian_memory.save_knowledge("Nota do Usuário", note_content, tags=["nota-rapida", "memoria-pessoal"])
            return {"type": "memory_note", "command": raw_text, "response_speech": speech, "display_text": speech}

        recall_match = re.search(r"(?:o que você lembra sobre|o que tem na memória sobre|buscar na memória|pesquisar na memória sobre)\s+(.+)", text)
        if recall_match:
            from core.memory_obsidian import obsidian_memory
            query_term = recall_match.group(1).strip()
            mem_res = obsidian_memory.search_memory(query_term)
            if mem_res:
                speech = f"Consultei nosso cofre Obsidian, {config.USER_NAME}. Encontrei o seguinte: {mem_res}"
            else:
                speech = f"Não encontrei registros anteriores sobre '{query_term}' no cofre do Obsidian, {config.USER_NAME}."
            return {"type": "memory_recall", "command": raw_text, "response_speech": speech, "display_text": speech}

        # 12. PURE GREETINGS (Only if no specific action was asked)
        pure_greetings = ["olá", "oi", "bom dia", "boa tarde", "boa noite", "está aí", "você está acordado", "tudo bem", "e aí"]
        if cleaned in pure_greetings or text in pure_greetings:
            now_hour = datetime.now().hour
            saudacao = "Bom dia" if now_hour < 12 else ("Boa tarde" if now_hour < 18 else "Boa noite")
            speech = f"{saudacao}, {config.USER_NAME}. Sistemas neurais operacionais e à sua disposição."
            return {"type": "greeting", "command": raw_text, "response_speech": speech, "display_text": speech}

        # 13. WEB RESEARCH SYNTHESIS
        if any(p in text for p in ["pesquise sobre", "pesquisar sobre", "o que é", "quem é", "quem foi", "notícias sobre", "me fale sobre"]):
            search_match = re.search(r"(?:pesquise sobre|pesquisar sobre|o que é|quem é|quem foi|notícias sobre|me fale sobre)\s+(.+)", text)
            if search_match:
                query = search_match.group(1).replace("para mim", "").replace("por favor", "").strip()
                speech = llm_brain.search_and_synthesize(query)
                return {"type": "web_research", "command": raw_text, "response_speech": speech, "display_text": speech}

        # 14. HERMES COGNITIVE AGENT & OBSIDIAN MEMORY (General Fallback)
        speech, display, thought = llm_brain.ask_full(raw_text)
        return {
            "type": "conversation",
            "command": raw_text,
            "response_speech": speech,
            "display_text": display,
            "thought": thought
        }

command_dispatcher = CommandDispatcher()
