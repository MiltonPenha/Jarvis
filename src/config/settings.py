from pathlib import Path

# Raiz do projeto
BASE_DIR = Path(__file__).resolve().parents[2]

# Pastas de dados
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = DATA_DIR / "logs"
CACHE_DIR = DATA_DIR / "cache"
MEMORY_DIR = DATA_DIR / "memory"

# Áudio
AUDIO_SAMPLE_RATE = 16_000
AUDIO_CHANNELS = 1
AUDIO_DTYPE = "float32"
DEFAULT_RECORD_SECONDS = 5

# Wake word e idioma
WAKE_WORD = "jarvis"
LANGUAGE = "pt"

# LLM
MODEL_NAME = "qwen3.5:9b"