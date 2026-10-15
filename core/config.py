"""Backend configuration. Credentials never enter public settings."""
import json
import os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env', override=False)
# A nonempty project credential is an explicit user choice. Empty example fields
# keep inherited credentials, while inherited placeholders cannot mask a new key.
for _key,_value in dotenv_values(BASE_DIR/'.env').items():
    if _key in ('OPENAI_API_KEY','GEMINI_API_KEY','GOOGLE_API_KEY') and _value:
        os.environ[_key]=_value

class Config:
    BASE_DIR = BASE_DIR
    WEB_DIR = BASE_DIR / 'web'
    COMMANDS_FILE = BASE_DIR / 'commands.json'
    DATA_DIR = Path(os.getenv('JARVIS_DATA_DIR', str(BASE_DIR / '.data'))).resolve()
    HERMES_HOME = Path(os.getenv('JARVIS_HERMES_HOME', str(DATA_DIR / 'hermes'))).resolve()
    HERMES_SOURCE = Path(os.getenv('HERMES_SOURCE', str(BASE_DIR / '.runtime/hermes-agent'))).resolve()
    HERMES_PYTHON = os.getenv('HERMES_PYTHON', '')
    OBSIDIAN_VAULT_PATH = os.getenv('OBSIDIAN_VAULT_PATH', str(DATA_DIR / 'vault'))
    WORKSPACE_ROOTS = [Path(p).resolve() for p in os.getenv('JARVIS_WORKSPACE_ROOTS', str(BASE_DIR / 'workspace')).split(';') if p]
    HOST = os.getenv('HOST', '127.0.0.1')
    PORT = int(os.getenv('PORT', '8000'))
    WHISPER_PATH = Path(os.getenv('JARVIS_WHISPER_PATH',str(DATA_DIR/'models/whisper-base'))).resolve()
    AUTOSTART_NAME = 'JarvisAI'
    TTS_VOICE = os.getenv('JARVIS_TTS_VOICE', 'pt-BR-AntonioNeural')
    TTS_RATE = os.getenv('JARVIS_TTS_RATE', '-4%')
    TTS_PITCH = os.getenv('JARVIS_TTS_PITCH', '-2Hz')
    TTS_PROVIDER = os.getenv('JARVIS_TTS_PROVIDER', 'offline')
    STT_PROVIDER = os.getenv('JARVIS_STT_PROVIDER', 'whisper-local')
    OPENAI_TTS_MODEL = os.getenv('OPENAI_TTS_MODEL', '')
    OPENAI_TTS_VOICE = os.getenv('OPENAI_TTS_VOICE', 'onyx')
    OPENAI_STT_MODEL = os.getenv('OPENAI_STT_MODEL', '')
    STT_LANGUAGE = 'pt-BR'
    VAD_THRESHOLD = float(os.getenv('JARVIS_VAD_THRESHOLD','0.004'))
    INPUT_DEVICE = os.getenv('JARVIS_INPUT_DEVICE') or None
    OUTPUT_DEVICE = os.getenv('JARVIS_OUTPUT_DEVICE') or None
    MAX_STEPS = int(os.getenv('JARVIS_MAX_STEPS', '6'))
    MAX_OUTPUT_TOKENS = int(os.getenv('JARVIS_MAX_OUTPUT_TOKENS', '1500'))
    MAX_CONTEXT_CHARS = int(os.getenv('JARVIS_MAX_CONTEXT_CHARS', '24000'))
    TASK_TIMEOUT = int(os.getenv('JARVIS_TASK_TIMEOUT', '120'))
    MAX_DAILY_TASKS = int(os.getenv('JARVIS_MAX_DAILY_TASKS', '30'))
    MAX_DAILY_TOKENS = int(os.getenv('JARVIS_MAX_DAILY_TOKENS', '100000'))
    MAX_TOOL_CHARS = 6000
    MAX_FILE_BYTES = 2_000_000

config = Config()

def settings():
    defaults = {
        'provider': os.getenv('JARVIS_PROVIDER', 'openai-api'), 'model': os.getenv('JARVIS_MODEL', ''),
        'fallback_provider': os.getenv('JARVIS_FALLBACK_PROVIDER', ''), 'fallback_model': os.getenv('JARVIS_FALLBACK_MODEL', ''),
        'tts_provider': config.TTS_PROVIDER, 'tts_voice': config.TTS_VOICE,
        'stt_provider': config.STT_PROVIDER, 'speech_enabled': True,
        'input_device':config.INPUT_DEVICE or '',
        'input_price_per_million': None, 'output_price_per_million': None, 'prices_updated': None,
    }
    path = config.DATA_DIR / 'settings.json'
    if path.exists():
        defaults.update({k:v for k,v in json.loads(path.read_text(encoding='utf-8')).items() if k in defaults})
    return defaults

def provider_key(provider):
    if provider == 'openai-api':
        return os.getenv('OPENAI_API_KEY', '')
    if provider == 'gemini':
        return os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY', '')
    return ''
