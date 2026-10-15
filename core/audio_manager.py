"""One microphone owner and one cancellable playback path. No startup recording."""
import asyncio
import io
import logging
import re
import tempfile
import threading
import time
from pathlib import Path
from core.config import config, settings, provider_key

logger = logging.getLogger('JarvisAudio')

def speech_text(text,limit=700):
    text = re.sub(r'```.*?```',' Os detalhes do código estão na tela. ',text,flags=re.S)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)',r'\1',text)
    text = re.sub(r'https?://\S+','',text)
    text = re.sub(r'<[^>]+>','',text)
    lines = [line for line in text.splitlines() if not line.lstrip().startswith(('|','Traceback','File "'))]
    text = re.sub(r'[`*_#>~]','', ' '.join(lines))
    text = re.sub(r'\s+',' ',text).strip()
    if len(text)>limit:
        shortened = text[:limit]
        point = max(shortened.rfind('.'),shortened.rfind('!'),shortened.rfind('?'))
        text = shortened[:point+1] if point>limit//2 else shortened.rsplit(' ',1)[0]+'.'
        text += ' Os detalhes completos estão na tela.'
    return text

class AudioManager:
    def __init__(self):
        self.is_listening = False
        self.is_speaking = False
        self.enabled = True
        self.on_state_change = None
        self.on_audio_level = None
        self._cancel = threading.Event()
        self._mic_lock = threading.Lock()
        self._speech_lock = threading.Lock()
        self._whisper = None
        self._pyttsx_engine = None
        self._generation = 0

    def notify_state(self,state):
        if self.on_state_change:
            self.on_state_change(state)

    def stop(self):
        self._generation += 1
        self._cancel.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        if self._pyttsx_engine:
            try:
                self._pyttsx_engine.stop()
            except Exception:
                pass

    async def synthesize(self,text,path,provider=None):
        s = settings()
        provider = provider or s['tts_provider']
        text = speech_text(text)
        if provider=='edge':
            import edge_tts
            voice = s['tts_voice']
            await asyncio.wait_for(edge_tts.Communicate(text,voice,rate=config.TTS_RATE,pitch=config.TTS_PITCH).save(str(path)),25)
        elif provider=='openai':
            from openai import AsyncOpenAI
            if not config.OPENAI_TTS_MODEL:
                raise ValueError('Configure OPENAI_TTS_MODEL antes de usar voz OpenAI.')
            async with AsyncOpenAI(api_key=provider_key('openai-api'),timeout=25,max_retries=1) as client:
                result = await client.audio.speech.create(model=config.OPENAI_TTS_MODEL,voice=config.OPENAI_TTS_VOICE,input=text)
                path.write_bytes(result.content)
        else:
            raise ValueError('Síntese em arquivo não disponível neste provedor.')

    def speak(self,text,wait=True):
        text = speech_text(text)
        if not text or not self.enabled:
            return {'state':'disabled'}
        generation = self._generation
        if not self._speech_lock.acquire(blocking=False):
            return {'state':'busy'}
        path = None
        try:
            if generation!=self._generation:
                return {'state':'cancelled'}
            self._cancel.clear()
            self.is_speaking = True
            self.notify_state('SPEAKING')
            provider = settings()['tts_provider']
            if provider=='offline':
                import pyttsx3
                engine = pyttsx3.init()
                self._pyttsx_engine = engine
                engine.setProperty('rate',config.OFFLINE_TTS_RATE)
                for voice in engine.getProperty('voices'):
                    if 'brazil' in voice.name.lower() or 'pt-br' in voice.id.lower():
                        engine.setProperty('voice',voice.id)
                        break
                if not self._cancel.is_set():
                    engine.say(text)
                    engine.runAndWait()
            else:
                import sounddevice as sd
                import soundfile as sf
                with tempfile.NamedTemporaryFile(suffix='.mp3',delete=False) as f:
                    path = Path(f.name)
                asyncio.run(self.synthesize(text,path,provider))
                if self._cancel.is_set():
                    return {'state':'cancelled'}
                data,rate = sf.read(path,dtype='float32')
                # Generation is checked after network synthesis; cancelled audio never starts.
                if generation!=self._generation:
                    return {'state':'cancelled'}
                sd.play(data,rate,device=config.OUTPUT_DEVICE)
                # Waiting in short slices permits a hard playback stop.
                deadline = time.monotonic()+len(data)/rate
                while time.monotonic()<deadline and not self._cancel.wait(.05):
                    pass
                sd.stop()
            return {'state':'cancelled' if self._cancel.is_set() else 'completed'}
        except Exception as exc:
            # No hidden provider fallback: failures stay visible and text remains usable.
            return {'state':'failed','error':type(exc).__name__+': voz indisponível; veja a configuração.'}
        finally:
            if path:
                path.unlink(missing_ok=True)
            self._pyttsx_engine = None
            self.is_speaking = False
            self._speech_lock.release()

    def record_phrase(self,samplerate=16000,max_seconds=12,silence_limit=.9):
        import sounddevice as sd
        import numpy as np
        block = int(samplerate*.05)
        chunks = []
        preroll = []
        speech_start = None
        last_voice = None
        started = time.monotonic()
        with sd.InputStream(samplerate=samplerate,channels=1,dtype='float32',blocksize=block,device=config.INPUT_DEVICE) as stream:
            while not self._cancel.is_set():
                chunk,overflow = stream.read(block)
                if self.is_speaking:
                    return None
                rms = float(np.sqrt(np.mean(chunk**2)))
                if self.on_audio_level:
                    self.on_audio_level(min(1.,rms*10))
                current = time.monotonic()
                if rms>config.VAD_THRESHOLD:
                    if speech_start is None:
                        speech_start = current
                        chunks.extend(preroll)
                    last_voice = current
                if speech_start is not None:
                    chunks.append(chunk.copy())
                    if current-last_voice>silence_limit or current-speech_start>=max_seconds:
                        break
                else:
                    preroll = (preroll+[chunk.copy()])[-4:]
                    if current-started>8:
                        return None
        return np.concatenate(chunks,axis=0) if chunks and not self._cancel.is_set() else None

    def transcribe_audio(self,audio_data,samplerate=16000):
        import soundfile as sf
        if audio_data is None:
            return None
        provider = settings()['stt_provider']
        if provider=='whisper-local':
            if self._whisper is None:
                from faster_whisper import WhisperModel
                self._whisper = WhisperModel('base',device='cpu',compute_type='int8')
            segments,_ = self._whisper.transcribe(audio_data.flatten(),language='pt',vad_filter=True)
            return ' '.join(s.text for s in segments).strip()
        buffer = io.BytesIO()
        sf.write(buffer,audio_data,samplerate,format='WAV',subtype='PCM_16')
        buffer.seek(0)
        if provider=='openai':
            from openai import OpenAI
            if not config.OPENAI_STT_MODEL:
                raise ValueError('Configure OPENAI_STT_MODEL.')
            buffer.name = 'speech.wav'
            with OpenAI(api_key=provider_key('openai-api'),timeout=20,max_retries=1) as client:
                result = client.audio.transcriptions.create(file=buffer,model=config.OPENAI_STT_MODEL,language='pt')
                return result.text.strip()
        if provider!='google-web':
            raise ValueError('Provedor de transcrição inválido.')
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        recognizer.operation_timeout = 12
        with sr.AudioFile(buffer) as source:
            sample = recognizer.record(source)
        try:
            return recognizer.recognize_google(sample,language=config.STT_LANGUAGE).strip()
        except sr.UnknownValueError:
            return None

    def listen_and_transcribe(self):
        if not self.enabled or self.is_speaking or not self._mic_lock.acquire(blocking=False):
            return None
        self._cancel.clear()
        generation = self._generation
        self.is_listening = True
        try:
            self.notify_state('LISTENING')
            audio = self.record_phrase()
            if self._cancel.is_set():
                return None
            self.notify_state('PROCESSING')
            text = self.transcribe_audio(audio)
            return text if generation==self._generation else None
        finally:
            self.is_listening = False
            self._mic_lock.release()

audio_manager = AudioManager()
