import os
import sys
import time
import socket
import logging
import threading
import subprocess
import webbrowser
from pathlib import Path

import uvicorn

from core.config import config
from core.audio_manager import audio_manager
from core.command_patterns import command_dispatcher
from core.autostart import autostart_service
import server

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("JARVIS-CORE")

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def launch_hud_window(port: int):
    """
    Launches the HUD interface in application mode (frameless standalone window).
    Prefers Google Chrome or Microsoft Edge app mode for the ultimate sci-fi feel.
    """
    url = f"http://127.0.0.1:{port}"
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]

    # Try Chrome App Mode
    for cp in chrome_paths:
        if Path(cp).exists():
            logger.info("Iniciando HUD holográfico via Chrome App Mode...")
            subprocess.Popen([cp, f"--app={url}", "--window-size=1300,850"])
            return True

    # Try Edge App Mode
    for ep in edge_paths:
        if Path(ep).exists():
            logger.info("Iniciando HUD holográfico via Edge App Mode...")
            subprocess.Popen([ep, f"--app={url}", "--window-size=1300,850"])
            return True

    # Default browser fallback
    logger.info("Abrindo HUD no navegador padrão...")
    webbrowser.open(url)
    return True

def background_voice_listener():
    """
    Continuous background voice loop:
    Listens for wake words ("Jarvis", "Ei Jarvis", etc.) or commands,
    processes them and speaks the response.
    """
    logger.info("Módulo de escuta contínua por voz ativado.")
    time.sleep(2.5) # Allow server and HUD to initialize

    while True:
        try:
            if audio_manager.is_speaking:
                time.sleep(0.3)
                continue

            # Listen to microphone
            phrase = audio_manager.listen_and_transcribe()
            if not phrase:
                continue

            logger.info(f"[VOZ CAPTADA]: {phrase}")
            lower_phrase = phrase.lower().strip()

            # Check if wake word was invoked or direct command given
            is_wake = any(w in lower_phrase for w in config.WAKE_WORDS)

            # If wake word was detected or assistant is already active
            if is_wake or len(lower_phrase.split()) >= 2:
                # Play confirmation sound
                audio_manager.play_chime(wake=True)

                # Execute command
                result = command_dispatcher.execute_command(phrase)

                # Broadcast to server / HUD
                speech = result.get("response_speech", "")
                display = result.get("display_text", speech)

                # Send to connected HUD clients
                import asyncio
                if server.active_connections:
                    try:
                        asyncio.run(server.broadcast_message(
                            server.json.dumps({
                                "type": "user_command",
                                "text": phrase
                            })
                        ))
                        asyncio.run(server.broadcast_message(
                            server.json.dumps({
                                "type": "jarvis_response",
                                "command": phrase,
                                "response": display
                            })
                        ))
                    except Exception:
                        pass

                # Speak the response
                if speech:
                    audio_manager.speak(speech)
                    audio_manager.play_chime(wake=False)

        except Exception as e:
            logger.error(f"Erro no ciclo de voz: {e}")
            time.sleep(1.0)

def main():
    print(r"""
    ========================================================
       _______.  ___      .______     ____    ____  __       _______.
      /       | /   \     |   _  \    \   \  /   / |  |     /       |
     |   (----`/  ^  \    |  |_)  |    \   \/   /  |  |    |   (----`
      \   \   /  /_\  \   |      /      \      /   |  |     \   \    
  .----)   | /  _____  \  |  |\  \----.  \    /    |  | .----)   |   
  |_______/ /__/     \__\ | _| `._____|   \__/     |__| |_______/    
    
        SISTEMA DE INTELIGÊNCIA ARTIFICIAL PESSOAL v3.0
                   [GOLDEN HOLOGRAPHIC CORE]
    ========================================================
    """)

    # 1. Ensure Windows Startup scripts are ready
    autostart_service._ensure_launcher_scripts()
    is_boot_enabled = autostart_service.is_enabled()
    logger.info(f"Status de Inicialização no Boot do Windows: {'ATIVADO' if is_boot_enabled else 'DESATIVADO'}")

    port = config.PORT
    
    # 2. Start FastAPI Server in Background Thread
    def run_uvicorn():
        uvicorn.run(server.app, host=config.HOST, port=port, log_level="warning")

    server_thread = threading.Thread(target=run_uvicorn, daemon=True)
    server_thread.start()
    logger.info(f"Servidor JARVIS ativo em http://{config.HOST}:{port}")

    # Give server a second to start
    time.sleep(1.0)

    # 3. Launch HUD Interface Window
    hud_proc = launch_hud_window(port)

    # 4. Greet User with Speech
    def welcome_greeting():
        time.sleep(1.2)
        greeting = f"Sistemas neurais e cofre de memória inicializados, {config.USER_NAME}. J.A.R.V.I.S. online e pronto para suas instruções."
        audio_manager.speak(greeting)

    threading.Thread(target=welcome_greeting, daemon=True).start()

    # 5. Start Voice Listener Loop (runs in background thread)
    voice_thread = threading.Thread(target=background_voice_listener, daemon=True)
    voice_thread.start()

    # Keep JARVIS alive and operational
    # It will safely terminate when the user clicks 'ENCERRAR' (⏻), says 'Jarvis, encerrar', or runs PARAR_JARVIS.bat
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Encerrando JARVIS...")
        os._exit(0)

if __name__ == "__main__":
    main()
