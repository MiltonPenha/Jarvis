"""Optional real voice test: generated speech only, no microphone recording or playback."""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.audio_manager import audio_manager
from core.config import config,settings
from core.safety import atomic_write

async def main():
    result={'perceptual_evaluation':False,'microphone_recorded':False,'tts_provider':settings()['tts_provider'],'stt_provider':settings()['stt_provider']}
    provider=settings()['tts_provider']
    name='voice-neural.wav' if provider=='piper' else 'voice-local.wav' if provider=='offline' else 'voice.mp3'
    target=config.DATA_DIR/'validation'/name
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        await audio_manager.synthesize('JARVIS, diga o status do sistema.',target)
        import soundfile as sf
        import numpy as np
        data,rate=sf.read(target,dtype='float32')
        if data.ndim>1:data=np.mean(data,axis=1)
        if not len(data) or not np.isfinite(data).all():raise ValueError('Áudio inválido.')
        result.update(tts_verified=True,bytes=target.stat().st_size,seconds=round(len(data)/rate,2),sample_rate=rate)
        text=await asyncio.to_thread(audio_manager.transcribe_audio,data,rate)
        result.update(stt_verified=bool(text),transcript=text)
    except Exception as exc:
        result['error']=type(exc).__name__+': '+str(exc)[:400]
    import sounddevice as sd
    try:result['input_devices']=sum(1 for d in sd.query_devices() if d['max_input_channels']>0)
    except Exception:result['input_devices']=None
    atomic_write(target.with_suffix('.json'),json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
