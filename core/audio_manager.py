"""One microphone owner and one cancellable playback path. No startup recording."""
import asyncio
import io
import re
import tempfile
import threading
import time
from pathlib import Path
from core.config import config, settings, provider_key

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
        self.is_speaking = False
        self.on_state_change = None
        self.on_audio_level = None
        self._cancel = threading.Event()
        self._mic_lock = threading.Lock()
        self._speech_lock = threading.Lock()
        self._whisper = None
        self._whisper_lock = threading.Lock()
        self._generation = 0
        self.last_capture = {}

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

    def prepare_local_transcriber(self):
        with self._whisper_lock:
            if self._whisper is None:
                if not (config.WHISPER_PATH/'model.bin').is_file():
                    raise ValueError('Whisper local não preparado. Execute scripts/setup_voice.ps1.')
                from faster_whisper import WhisperModel
                self._whisper=WhisperModel(str(config.WHISPER_PATH),device='cpu',compute_type='int8',
                                          cpu_threads=4,num_workers=1,local_files_only=True)
        return self._whisper

    @staticmethod
    def synthesize_windows(text,path):
        import pythoncom
        from win32com.client import Dispatch
        pythoncom.CoInitialize()
        stream=None
        try:
            voice=Dispatch('SAPI.SpVoice')
            voices=list(voice.GetVoices())
            brazilian=next((v for v in voices if '416' in v.GetAttribute('Language').lower().split(';')),None)
            if brazilian is None:raise ValueError('Instale uma voz Português (Brasil) nas configurações de fala do Windows.')
            voice.Voice=brazilian;voice.Rate=0;voice.Volume=100
            stream=Dispatch('SAPI.SpFileStream');stream.Open(str(path.resolve()),3,False)
            voice.AudioOutputStream=stream
            voice.Speak(text,0)
        finally:
            if stream:stream.Close()
            pythoncom.CoUninitialize()

    async def synthesize(self,text,path,provider=None):
        s = settings()
        provider = provider or s['tts_provider']
        text = speech_text(text)
        if provider=='piper':
            from core.neural_voice import neural_voice
            await asyncio.to_thread(neural_voice.synthesize,text,path)
        elif provider=='offline':
            await asyncio.to_thread(self.synthesize_windows,text,path)
        elif provider=='edge':
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

    def speak(self,text):
        text = speech_text(text)
        if not text:
            return {'state':'empty'}
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
            import sounddevice as sd
            import soundfile as sf
            with tempfile.NamedTemporaryFile(suffix='.wav' if provider in ('offline','piper') else '.mp3',delete=False) as f:
                path = Path(f.name)
            asyncio.run(self.synthesize(text,path,provider))
            if self._cancel.is_set():
                return {'state':'cancelled'}
            data,rate = sf.read(path,dtype='float32')
            if generation!=self._generation:
                return {'state':'cancelled'}
            sd.play(data,rate,device=config.OUTPUT_DEVICE)
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
            self.is_speaking = False
            self._speech_lock.release()

    def record_phrase(self,samplerate=16000,max_seconds=12,silence_limit=.9):
        import sounddevice as sd
        import numpy as np
        from core.audio_devices import capture_parameters
        device,samplerate=capture_parameters(settings()['input_device'],samplerate)
        self.last_capture={'device':device['name'],'hostapi':device['hostapi'],'sample_rate':samplerate,
                           'threshold':config.VAD_THRESHOLD,'peak_rms':0.,'speech_detected':False,'reason':'listening'}
        block = int(samplerate*.05)
        chunks = []
        preroll = []
        speech_start = None
        last_voice = None
        started = time.monotonic()
        with sd.InputStream(samplerate=samplerate,channels=1,dtype='float32',blocksize=block,device=device['index']) as stream:
            while not self._cancel.is_set():
                chunk,overflow = stream.read(block)
                if self.is_speaking:
                    return None
                rms = float(np.sqrt(np.mean(chunk**2)))
                self.last_capture['peak_rms']=max(self.last_capture['peak_rms'],rms)
                if self.on_audio_level:
                    self.on_audio_level(min(1.,rms*10))
                current = time.monotonic()
                if rms>config.VAD_THRESHOLD:
                    if speech_start is None:
                        speech_start = current
                        chunks.extend(preroll)
                        self.last_capture['speech_detected']=True
                    last_voice = current
                if speech_start is not None:
                    chunks.append(chunk.copy())
                    if current-last_voice>silence_limit or current-speech_start>=max_seconds:
                        self.last_capture['reason']='silence' if current-last_voice>silence_limit else 'max_duration'
                        break
                else:
                    preroll = (preroll+[chunk.copy()])[-4:]
                    if current-started>8:
                        self.last_capture['reason']='no_signal'
                        return None
        if self._cancel.is_set():self.last_capture['reason']='cancelled'
        return np.concatenate(chunks,axis=0) if chunks and not self._cancel.is_set() else None

    def transcribe_audio(self,audio_data,samplerate=16000):
        import soundfile as sf
        if audio_data is None:
            return None
        provider = settings()['stt_provider']
        if provider=='whisper-local':
            if samplerate!=16000:
                import numpy as np
                samples=audio_data.flatten()
                audio_data=np.interp(np.arange(round(len(samples)*16000/samplerate))*samplerate/16000,
                                     np.arange(len(samples)),samples).astype(np.float32)
            transcriber=self.prepare_local_transcriber()
            segments,_ = transcriber.transcribe(audio_data.flatten(),language='pt',vad_filter=True,
                beam_size=1,best_of=1,condition_on_previous_text=False)
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
        if self.is_speaking or not self._mic_lock.acquire(blocking=False):
            return None
        self._cancel.clear()
        generation = self._generation
        try:
            self.notify_state('LISTENING')
            audio = self.record_phrase()
            if self._cancel.is_set():
                return None
            if audio is None:
                return None
            self.notify_state('PROCESSING')
            text = self.transcribe_audio(audio,samplerate=self.last_capture.get('sample_rate',16000))
            self.last_capture['transcribed']=bool(text)
            return text if generation==self._generation else None
        finally:
            self._mic_lock.release()

audio_manager = AudioManager()
