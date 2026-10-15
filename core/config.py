import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
ASSETS_DIR = WEB_DIR / "assets"
COMMANDS_FILE = BASE_DIR / "commands.json"
ENV_FILE = BASE_DIR / ".env"

# Load .env if exists
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    load_dotenv()

class Config:
    BASE_DIR = BASE_DIR
    WEB_DIR = WEB_DIR
    ASSETS_DIR = ASSETS_DIR
    COMMANDS_FILE = COMMANDS_FILE
    ENV_FILE = ENV_FILE

    # System Info
    ASSISTANT_NAME = os.getenv("JARVIS_NAME", "JARVIS")
    USER_NAME = os.getenv("USER_NAME", "Senhor")
    PORT = int(os.getenv("PORT", 8000))
    HOST = os.getenv("HOST", "127.0.0.1")
    
    # Audio & Voice Settings
    WAKE_WORDS = [
        "jarvis",
        "jarbas",
        "jervis",
        "iarvis",
        "iarbas",
        "jabis",
        "jarve",
        "jarves",
        "chaves",
        "ei jarvis",
        "ei jarbas",
        "olá jarvis",
        "olá jarbas",
        "oi jarvis",
        "oi jarbas",
        "e aí jarvis",
        "e aí jarbas",
        "ok jarvis",
        "ok jarbas"
    ]
    
    # TTS Voice: British JARVIS Voice (en-GB-RyanNeural)
    TTS_VOICE = os.getenv("TTS_VOICE", "en-GB-RyanNeural")
    TTS_RATE = os.getenv("TTS_RATE", "-4%")
    TTS_PITCH = os.getenv("TTS_PITCH", "-6Hz")
    
    # Fallback offline voice (pyttsx3)
    OFFLINE_TTS_RATE = int(os.getenv("OFFLINE_TTS_RATE", 190))
    OFFLINE_TTS_VOLUME = float(os.getenv("OFFLINE_TTS_VOLUME", 1.0))
    
    # Speech Recognition
    STT_LANGUAGE = os.getenv("STT_LANGUAGE", "pt-BR")
    MIC_ENERGY_THRESHOLD = int(os.getenv("MIC_ENERGY_THRESHOLD", 1000))
    MIC_PAUSE_THRESHOLD = float(os.getenv("MIC_PAUSE_THRESHOLD", 0.8))
    
    # Obsidian Memory Vault
    OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", r"C:\Users\PC Gamer\Documents\JARVIS-Memory")
    
    # AI Brain Keys & Hermes Agent
    HERMES_MODEL = os.getenv("HERMES_MODEL", "hermes3:8b")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "hermes3:8b")
    
    # Startup on Windows
    AUTOSTART_NAME = "JarvisAI"

config = Config()
