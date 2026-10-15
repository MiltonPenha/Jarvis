import os
import json
import asyncio
import logging
import threading
from typing import List, Set
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.config import config
from core.system_monitor import system_monitor
from core.audio_manager import audio_manager
from core.command_patterns import command_dispatcher
from core.autostart import autostart_service

logger = logging.getLogger("JarvisServer")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="JARVIS Personal AI Assistant", version="2.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active WebSocket connections
active_connections: Set[WebSocket] = set()

class CommandRequest(BaseModel):
    command: str

class SpeakRequest(BaseModel):
    text: str

class CommandsUpdateRequest(BaseModel):
    custom_commands: list

@app.on_event("startup")
async def startup_event():
    # Link audio_manager callbacks to WebSocket broadcast
    def on_state(state):
        asyncio.run_coroutine_threadsafe(broadcast_state(state), loop)
        
    def on_level(level):
        asyncio.run_coroutine_threadsafe(broadcast_audio_level(level), loop)

    audio_manager.on_state_change = on_state
    audio_manager.on_audio_level = on_level

    global loop
    loop = asyncio.get_running_loop()
    # Start periodic telemetry broadcast
    asyncio.create_task(telemetry_broadcast_task())

async def broadcast_state(state: str):
    message = json.dumps({"type": "state", "state": state})
    await broadcast_message(message)

async def broadcast_audio_level(level: float):
    message = json.dumps({"type": "audio_level", "level": level})
    await broadcast_message(message)

async def broadcast_message(message: str):
    to_remove = set()
    for ws in list(active_connections):
        try:
            await ws.send_text(message)
        except Exception:
            to_remove.add(ws)
    for ws in to_remove:
        active_connections.discard(ws)

async def telemetry_broadcast_task():
    """Periodically broadcasts CPU, RAM and system telemetry to HUD."""
    while True:
        try:
            if active_connections:
                metrics = system_monitor.get_metrics()
                metrics["autostart_enabled"] = autostart_service.is_enabled()
                payload = json.dumps({"type": "telemetry", "data": metrics})
                await broadcast_message(payload)
        except Exception as e:
            logger.debug(f"Telemetry broadcast err: {e}")
        await asyncio.sleep(1.0)

# WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    try:
        # Send initial state and telemetry
        init_metrics = system_monitor.get_metrics()
        init_metrics["autostart_enabled"] = autostart_service.is_enabled()
        await websocket.send_text(json.dumps({
            "type": "init",
            "assistant_name": config.ASSISTANT_NAME,
            "user_name": config.USER_NAME,
            "telemetry": init_metrics
        }))

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                
                if action == "command":
                    user_cmd = msg.get("command", "")
                    if user_cmd:
                        # Process command asynchronously
                        asyncio.create_task(handle_user_command(user_cmd))
                        
                elif action == "listen_trigger":
                    # User clicked listen button on UI
                    asyncio.create_task(handle_listen_request())

                elif action == "toggle_autostart":
                    enabled = autostart_service.is_enabled()
                    if enabled:
                        success, text = autostart_service.disable()
                    else:
                        success, text = autostart_service.enable()
                    await websocket.send_text(json.dumps({
                        "type": "autostart_status",
                        "enabled": autostart_service.is_enabled(),
                        "message": text
                    }))

                elif action == "shutdown":
                    # Clean shutdown requested by UI
                    def _kill():
                        time.sleep(0.5)
                        os._exit(0)
                    threading.Thread(target=_kill, daemon=True).start()
                    return
                    
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        active_connections.discard(websocket)
    except Exception as e:
        active_connections.discard(websocket)

async def handle_user_command(user_cmd: str):
    """Executes a command, broadcasts response and speaks."""
    await broadcast_message(json.dumps({"type": "user_command", "text": user_cmd}))
    await broadcast_state("PROCESSING")

    # Run execution in background thread to avoid blocking server
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, command_dispatcher.execute_command, user_cmd)
    
    # Send result to UI
    await broadcast_message(json.dumps({
        "type": "jarvis_response",
        "command": user_cmd,
        "response": result.get("display_text", ""),
        "thought": result.get("thought"),
        "meta": result
    }))

    # Speak response
    speech = result.get("response_speech", "")
    if speech:
        await loop.run_in_executor(None, audio_manager.speak, speech)

async def handle_listen_request():
    """Listens to voice from microphone and handles the recognized text."""
    audio_manager.play_chime(wake=True)
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, audio_manager.listen_and_transcribe)
    if text:
        await handle_user_command(text)
    else:
        await broadcast_state("IDLE")

# REST API Endpoints
@app.post("/api/command")
def api_command(req: CommandRequest):
    result = command_dispatcher.execute_command(req.command)
    threading.Thread(target=audio_manager.speak, args=(result.get("response_speech", ""),), daemon=True).start()
    return result

@app.post("/api/speak")
def api_speak(req: SpeakRequest):
    threading.Thread(target=audio_manager.speak, args=(req.text,), daemon=True).start()
    return {"status": "speaking", "text": req.text}

@app.get("/api/status")
def api_status():
    metrics = system_monitor.get_metrics()
    metrics["autostart_enabled"] = autostart_service.is_enabled()
    return metrics

@app.post("/api/autostart/toggle")
def api_autostart_toggle():
    if autostart_service.is_enabled():
        success, msg = autostart_service.disable()
    else:
        success, msg = autostart_service.enable()
    return {"success": success, "enabled": autostart_service.is_enabled(), "message": msg}

@app.post("/api/shutdown")
def api_shutdown():
    def _kill():
        time.sleep(0.5)
        os._exit(0)
    threading.Thread(target=_kill, daemon=True).start()
    return {"status": "shutting_down"}

@app.get("/api/commands")
def api_get_commands():
    return {"custom_commands": command_dispatcher.load_custom_commands()}

@app.post("/api/commands")
def api_save_commands(req: CommandsUpdateRequest):
    with open(config.COMMANDS_FILE, "w", encoding="utf-8") as f:
        json.dump({"custom_commands": req.custom_commands}, f, indent=2, ensure_ascii=False)
    command_dispatcher.reload_custom_commands()
    return {"status": "saved"}

@app.get("/api/memory")
def api_get_memory():
    from core.memory_obsidian import obsidian_memory
    profile = obsidian_memory.get_user_profile()
    notes = [f.name for f in obsidian_memory.knowledge_dir.glob("*.md")]
    return {
        "vault_path": str(obsidian_memory.vault_dir),
        "profile": profile,
        "knowledge_notes": notes
    }

@app.post("/api/memory/open")
def api_open_memory():
    from core.memory_obsidian import obsidian_memory
    obsidian_memory.open_vault_folder()
    return {"status": "opened", "vault": str(obsidian_memory.vault_dir)}

# Static Files & UI
app.mount("/static", StaticFiles(directory=str(config.WEB_DIR)), name="static")

@app.get("/")
def get_index():
    return FileResponse(str(config.WEB_DIR / "index.html"))
