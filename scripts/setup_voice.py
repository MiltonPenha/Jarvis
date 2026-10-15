"""Prepare offline speech; preserve the configured AI provider, model and credentials."""
from datetime import datetime,timezone
import json
import hashlib
import os
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.config import config,settings
from core.safety import atomic_write
from dotenv import set_key

PIPER_REVISION='c10ece1aade47bb51c153c893d14e5bf8e5b7117'
PIPER_FILES={
    'pt_BR-faber-medium.onnx':'858555e3a064209c57088fe6bd70c4c3dc54d03eaa00c45d5ecaf43a33f95aa7',
    'pt_BR-faber-medium.onnx.json':'7e694de195ae3fc36dd732c445eb04fb49b649854893cb5506b978f0d50a1d6f',
    'MODEL_CARD':'01f1a5bcfd0538782726059ae407eae9c2dd1b5b35f7298fd53a68de91afe563',
}

def prepare_piper():
    folder=config.PIPER_MODEL_PATH.parent;folder.mkdir(parents=True,exist_ok=True)
    if config.PIPER_MODEL_PATH.name!='pt_BR-faber-medium.onnx':
        if not config.PIPER_MODEL_PATH.is_file():raise ValueError('Prepare o modelo personalizado de voz antes de selecioná-lo.')
        return
    import httpx
    with httpx.Client(timeout=90,follow_redirects=True) as client:
        for name,expected in PIPER_FILES.items():
            target=folder/name
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==expected:continue
            print('Preparando voz neural local: '+name,flush=True)
            temporary=target.with_suffix(target.suffix+'.part')
            try:
                url=f'https://huggingface.co/rhasspy/piper-voices/resolve/{PIPER_REVISION}/pt/pt_BR/faber/medium/{name}'
                with client.stream('GET',url) as response:
                    response.raise_for_status()
                    with temporary.open('wb') as output:
                        for chunk in response.iter_bytes(1024*1024):output.write(chunk)
                if hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected:raise ValueError('Checksum da voz neural não confere.')
                temporary.replace(target)
            finally:temporary.unlink(missing_ok=True)
    atomic_write(folder/'manifest.json',json.dumps({'repository':'rhasspy/piper-voices','revision':PIPER_REVISION,
        'voice':'pt_BR-faber-medium','dataset_license':'CC0','files':PIPER_FILES},indent=2))

def main():
    if not (config.WHISPER_PATH/'model.bin').is_file():
        from faster_whisper.utils import download_model
        print('Baixando Whisper base multilíngue para transcrição offline...',flush=True)
        download_model('base',output_dir=str(config.WHISPER_PATH))
    prepare_piper()
    backup=Path(os.environ.get('LOCALAPPDATA',config.BASE_DIR.parent))/'JarvisBackups'/('voice-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True,exist_ok=False)
    env=config.BASE_DIR/'.env';path=config.DATA_DIR/'settings.json'
    if env.exists():shutil.copy2(env,backup/'.env')
    else:shutil.copyfile(config.BASE_DIR/'.env.example',env)
    if path.exists():shutil.copy2(path,backup/'settings.json')
    values=settings();values.update(tts_provider='piper',stt_provider='whisper-local')
    atomic_write(path,json.dumps(values,ensure_ascii=False,indent=2))
    set_key(str(env),'JARVIS_TTS_PROVIDER','piper')
    set_key(str(env),'JARVIS_STT_PROVIDER','whisper-local')
    set_key(str(env),'JARVIS_PIPER_LENGTH_SCALE','1.18')
    print('Voz neural Faber e transcrição Whisper locais preparadas. Provedor e modelo de IA preservados.',flush=True)

if __name__=='__main__':main()
