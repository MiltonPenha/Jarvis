"""One microphone owner and one cancellable playback path. No startup recording."""
import asyncio
import io
import re
import tempfile
import threading
import time
from pathlib import Path
from core.config import config, settings, provider_key
from core.qwen_voice import qwen_voice, QwenVoiceError, QwenVoiceCancelled
from core.speech_text import prepare_speech as speech_text, speech_chunks

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
        self._state_local=threading.local()
        self.last_speech={}

    def notify_state(self,state):
        callback=getattr(self._state_local,'callback',None) or self.on_state_change
        if callback:callback(state)

    def stop(self):
        self._generation += 1
        self._cancel.set()
        qwen_voice.close()
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

    async def synthesize(self,text,path,provider=None,profile=None):
        s = settings()
        provider = provider or s['tts_provider']
        if provider not in ('qwen-local','piper','offline'):
            raise ValueError('A saída de voz aceita somente sintetizadores locais.')
        text = speech_text(text)
        if provider=='qwen-local':
            chunks=speech_chunks(text)
            if len(chunks)==1:
                await asyncio.to_thread(qwen_voice.synthesize,text,path,self._cancel)
            else:
                # Complete phrases are generated into one file before playback.
                # One output owner, native rate, no token fragments or gaps from inference.
                import wave
                with tempfile.TemporaryDirectory(prefix='jarvis-phrases-') as folder:
                    with wave.open(str(path),'wb') as output:
                        expected=None
                        for index,chunk in enumerate(chunks):
                            if self._cancel.is_set():raise QwenVoiceCancelled('Fala interrompida.')
                            self.last_speech.update(phase='generating',chunk=index+1,chunks=len(chunks),text=text)
                            self.notify_state('PROCESSING')
                            part=Path(folder)/f'{index}.wav'
                            await asyncio.to_thread(qwen_voice.synthesize,chunk,part,self._cancel)
                            with wave.open(str(part),'rb') as source:
                                signature=(source.getnchannels(),source.getsampwidth(),source.getframerate())
                                if expected is None:expected=signature;output.setparams(source.getparams())
                                elif signature!=expected:raise ValueError('Trechos com formatos de áudio diferentes.')
                                if index:output.writeframes(b'\0'*int(expected[2]*.12)*expected[0]*expected[1])
                                output.writeframes(source.readframes(source.getnframes()))
        elif provider=='piper':
            from core.neural_voice import neural_voice
            await asyncio.to_thread(neural_voice.synthesize,text,path,profile=profile or s.get('piper_profile','original'))
        elif provider=='offline':
            await asyncio.to_thread(self.synthesize_windows,text,path)
        else:
            raise ValueError('Síntese em arquivo não disponível neste provedor.')

    def speak(self,text,on_state=None,cancelled=lambda:False,provider=None,profile=None):
        text = speech_text(text)
        if not text:
            return {'state':'empty','delivered':False,'error':'A resposta falada estava vazia.'}
        generation = self._generation
        if not self._speech_lock.acquire(blocking=False):
            return {'state':'busy','delivered':False,'error':'A saída de voz estava ocupada; a resposta está na tela.'}
        microphone_reserved=False
        path = None
        try:
            microphone_reserved=self._mic_lock.acquire(timeout=5)
            if not microphone_reserved:return {'state':'busy','delivered':False,'error':'O microfone ainda estava capturando; a resposta está na tela.'}
            self._state_local.callback=on_state
            if generation!=self._generation or cancelled():
                return {'state':'cancelled'}
            self._cancel.clear()
            self.is_speaking = True
            started=time.monotonic()
            self.last_speech={'phase':'generating','text':text}
            self.notify_state('PROCESSING')
            provider = provider or settings()['tts_provider']
            import sounddevice as sd
            import soundfile as sf
            with tempfile.NamedTemporaryFile(suffix='.wav' if provider in ('offline','piper','qwen-local') else '.mp3',delete=False) as f:
                path = Path(f.name)
            if profile is None:asyncio.run(self.synthesize(text,path,provider))
            else:asyncio.run(self.synthesize(text,path,provider,profile=profile))
            if self._cancel.is_set() or cancelled():
                return {'state':'cancelled'}
            data,rate = sf.read(path,dtype='float32')
            import numpy as np
            if not len(data) or rate<=0 or not np.isfinite(data).all():raise ValueError('Áudio vazio ou inválido.')
            if generation!=self._generation or cancelled():
                return {'state':'cancelled'}
            duration=len(data)/rate
            self.last_speech={**self.last_speech,'phase':'playing','text':text,'provider':provider,'sample_rate':rate,'peak':float(np.max(np.abs(data))),'generation_seconds':round(time.monotonic()-started,3),'audio_seconds':round(duration,3),'delivered':False,'output_device':config.OUTPUT_DEVICE or 'Windows default'}
            sd.play(data,rate,device=config.OUTPUT_DEVICE)
            self.notify_state('SPEAKING')
            deadline = time.monotonic()+duration
            while time.monotonic()<deadline and generation==self._generation and not cancelled() and not self._cancel.wait(.05):
                pass
            stopped=self._cancel.is_set() or cancelled() or generation!=self._generation
            if stopped:sd.stop()
            else:
                status=sd.wait()
                if status:raise RuntimeError('Falha no fluxo de saída de áudio: '+str(status))
            self.last_speech['phase']='cancelled' if stopped else 'completed'
            self.last_speech['delivered']=not stopped
            return {'state':self.last_speech['phase'],**self.last_speech}
        except QwenVoiceCancelled:
            return {'state':'cancelled'}
        except (QwenVoiceError,ValueError) as exc:
            return {'state':'failed','error':str(exc)}
        except Exception as exc:
            # No hidden provider fallback: failures stay visible and text remains usable.
            from core.safety import redact
            return {'state':'failed','delivered':False,'error':type(exc).__name__+': voz indisponível; veja a configuração.',
                    'cause':redact(str(exc))[:500]}
        finally:
            try:
                if path:path.unlink(missing_ok=True)
            except OSError:pass
            finally:
                self.is_speaking = False
                self._speech_lock.release()
                if microphone_reserved:self._mic_lock.release()
                self._state_local.callback=None

    def record_phrase(self,samplerate=16000,max_seconds=None,silence_limit=None):
        import sounddevice as sd
        import numpy as np
        from core.audio_devices import capture_parameters
        device,samplerate=capture_parameters(settings()['input_device'],samplerate)
        max_seconds=max_seconds or config.VOICE_MAX_SECONDS
        silence_limit=silence_limit or config.VOICE_SILENCE_SECONDS
        self.last_capture={'device':device['name'],'hostapi':device['hostapi'],'sample_rate':samplerate,
                           'threshold':config.VAD_THRESHOLD,'peak_rms':0.,'speech_detected':False,'reason':'listening',
                           'silence_seconds':silence_limit,'preroll_seconds':config.VOICE_PREROLL_SECONDS,
                           'overflow_count':0,'peak_amplitude':0.,'clipped_samples':0}
        block = int(samplerate*.05)
        chunks = []
        preroll = []
        speech_start = None
        last_voice = None
        started = time.monotonic()
        with sd.InputStream(samplerate=samplerate,channels=1,dtype='float32',blocksize=block,device=device['index']) as stream:
            self.notify_state('LISTENING')
            while not self._cancel.is_set():
                chunk,overflow = stream.read(block)
                self.last_capture['overflow_count']+=int(overflow)
                self.last_capture['peak_amplitude']=max(self.last_capture['peak_amplitude'],float(np.max(np.abs(chunk))))
                self.last_capture['clipped_samples']+=int(np.sum(np.abs(chunk)>=.99))
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
                    preroll = (preroll+[chunk.copy()])[-max(1,round(config.VOICE_PREROLL_SECONDS/.05)):]
                    if current-started>8:
                        self.last_capture['reason']='no_signal'
                        return None
        if self._cancel.is_set():self.last_capture['reason']='cancelled'
        result=np.concatenate(chunks,axis=0) if chunks and not self._cancel.is_set() else None
        if result is not None:self.last_capture['duration_seconds']=round(len(result)/samplerate,3)
        return result

    def transcribe_audio(self,audio_data,samplerate=16000,vocabulary=''):
        import soundfile as sf
        if audio_data is None:
            return None
        provider = settings()['stt_provider']
        if provider=='whisper-local':
            if samplerate!=16000:
                import numpy as np
                import av
                frame=av.AudioFrame.from_ndarray(audio_data.reshape(1,-1).astype(np.float32),format='flt',layout='mono')
                frame.sample_rate=samplerate
                resampler=av.AudioResampler(format='flt',layout='mono',rate=16000)
                frames=resampler.resample(frame)+resampler.resample(None)
                audio_data=np.concatenate([frame.to_ndarray().flatten() for frame in frames]).astype(np.float32)
            transcriber=self.prepare_local_transcriber()
            hints=re.sub(r'\s+',' ',str(vocabulary)).strip()[:600]
            segments,_ = transcriber.transcribe(audio_data.flatten(),language='pt',vad_filter=True,
                beam_size=config.WHISPER_BEAM_SIZE,best_of=1,condition_on_previous_text=False,
                initial_prompt=(config.WHISPER_CONTEXT+' Vocabulário observado no pedido atual: '+hints if hints else config.WHISPER_CONTEXT) or None,
                hotwords=hints or None,temperature=0)
            rows=list(segments)
            self.last_capture['recognition']={'provider':provider,'model':config.WHISPER_PATH.name,'language':'pt',
                'beam_size':config.WHISPER_BEAM_SIZE,'segments':len(rows),
                'contextual_vocabulary':hints,'compute_type':'int8','device':'cpu',
                'average_log_probability':round(sum(getattr(s,'avg_logprob',0) for s in rows)/len(rows),3) if rows else None}
            return ' '.join(s.text for s in rows).strip()
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

    def listen_and_transcribe(self,on_state=None,vocabulary=''):
        if self.is_speaking or not self._mic_lock.acquire(blocking=False):
            return None
        self._cancel.clear()
        generation = self._generation
        try:
            self._state_local.callback=on_state
            audio = self.record_phrase()
            if self._cancel.is_set():
                return None
            if audio is None:
                return None
            self.notify_state('PROCESSING')
            from core.voice_diagnostics import retain_audio
            self.last_capture['retained_audio']=retain_audio(audio,self.last_capture.get('sample_rate',16000))
            started=time.monotonic()
            text = self.transcribe_audio(audio,samplerate=self.last_capture.get('sample_rate',16000),vocabulary=vocabulary)
            self.last_capture['transcribed']=bool(text)
            self.last_capture['transcription_seconds']=round(time.monotonic()-started,3)
            return text if generation==self._generation else None
        finally:
            self._mic_lock.release()
            self._state_local.callback=None

audio_manager = AudioManager()
