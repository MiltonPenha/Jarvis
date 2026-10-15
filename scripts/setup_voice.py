"""Prepare offline speech; preserve the configured AI provider, model and credentials."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.config import config,settings
from core.safety import atomic_write
from dotenv import set_key

def main():
    if not (config.WHISPER_PATH/'model.bin').is_file():
        from faster_whisper.utils import download_model
        print('Baixando Whisper base multilíngue para transcrição offline...',flush=True)
        download_model('base',output_dir=str(config.WHISPER_PATH))
    backup=Path(os.environ.get('LOCALAPPDATA',config.BASE_DIR.parent))/'JarvisBackups'/('voice-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True,exist_ok=False)
    env=config.BASE_DIR/'.env';path=config.DATA_DIR/'settings.json'
    if env.exists():shutil.copy2(env,backup/'.env')
    else:shutil.copyfile(config.BASE_DIR/'.env.example',env)
    if path.exists():shutil.copy2(path,backup/'settings.json')
    values=settings();values.update(tts_provider='offline',stt_provider='whisper-local')
    atomic_write(path,json.dumps(values,ensure_ascii=False,indent=2))
    set_key(str(env),'JARVIS_TTS_PROVIDER','offline')
    set_key(str(env),'JARVIS_STT_PROVIDER','whisper-local')
    print('Voz Windows e transcrição Whisper locais preparadas. Provedor e modelo de IA preservados.',flush=True)

if __name__=='__main__':main()
