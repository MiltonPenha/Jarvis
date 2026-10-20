"""Bounded requested voice diagnostics; raw recordings are opt-in and expire."""
import json
import time
import uuid
from core.config import config
from core.safety import file_lock,redact


def record_event(stage,**data):
    path=config.DATA_DIR/'logs/voice-events.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    event={'time':time.time(),'stage':stage,**data}
    with file_lock(path):
        if path.exists() and path.stat().st_size>1_000_000:path.replace(path.with_suffix('.previous.jsonl'))
        with path.open('a',encoding='utf-8') as stream:stream.write(redact(json.dumps(event,ensure_ascii=False))+'\n')


def retain_audio(audio,rate):
    folder=(config.DATA_DIR/'audio-diagnostics').resolve()
    if folder.is_dir():
        cutoff=time.time()-config.AUDIO_DIAGNOSTICS_HOURS*3600
        for path in folder.glob('voice-*.wav'):
            if path.is_file() and path.resolve().parent==folder and path.stat().st_mtime<cutoff:path.unlink()
    if config.AUDIO_DIAGNOSTICS_HOURS<=0:return None
    import soundfile as sf
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/('voice-'+uuid.uuid4().hex+'.wav');sf.write(path,audio,rate)
    return path.name
