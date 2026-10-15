import os
import io
import time
import math
import queue
import logging
import asyncio
import threading
import tempfile
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
import speech_recognition as sr
import edge_tts
import pyttsx3

from core.config import config

logger = logging.getLogger("JarvisAudio")
logging.basicConfig(level=logging.INFO)

class AudioManager:
    def __init__(self):
        self.is_listening = False
        self.is_speaking = False
        self.should_stop = False
        self._recognizer = sr.Recognizer()
        self._recognizer.energy_threshold = config.MIC_ENERGY_THRESHOLD
        self._recognizer.pause_threshold = config.MIC_PAUSE_THRESHOLD
        
        # Audio playback queue
        self.speech_queue = queue.Queue()
        self._playback_thread = None
        
        # Offline TTS engine (pyttsx3)
        self._pyttsx_engine = None
        self._init_pyttsx()
        
        # Callbacks for UI updates
        self.on_state_change: Optional[Callable[[str], None]] = None
        self.on_audio_level: Optional[Callable[[float], None]] = None
        self.on_transcription: Optional[Callable[[str, bool], None]] = None
        
        # Sound effects cache
        self._wake_chime = self._generate_sci_fi_chime(rising=True)
        self._confirm_chime = self._generate_sci_fi_chime(rising=False)
        
        # Temp dir for TTS
        self.temp_dir = Path(tempfile.gettempdir()) / "jarvis_tts"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def _init_pyttsx(self):
        try:
            self._pyttsx_engine = pyttsx3.init()
            self._pyttsx_engine.setProperty('rate', config.OFFLINE_TTS_RATE)
            self._pyttsx_engine.setProperty('volume', config.OFFLINE_TTS_VOLUME)
            voices = self._pyttsx_engine.getProperty('voices')
            for v in voices:
                if 'pt' in v.id.lower() or 'brazil' in v.name.lower() or 'maria' in v.name.lower():
                    self._pyttsx_engine.setProperty('voice', v.id)
                    break
        except Exception as e:
            logger.warning(f"Não foi possível inicializar pyttsx3: {e}")
            self._pyttsx_engine = None

    def _generate_sci_fi_chime(self, rising: bool = True) -> tuple[np.ndarray, int]:
        """Generates a high-tech synthesized sound cue."""
        sr_rate = 44100
        duration = 0.18
        t = np.linspace(0, duration, int(sr_rate * duration), False)
        
        if rising:
            freq1, freq2 = 800.0, 1400.0
            wave1 = 0.3 * np.sin(2 * np.pi * freq1 * t[:len(t)//2]) * np.exp(-12 * t[:len(t)//2])
            wave2 = 0.4 * np.sin(2 * np.pi * freq2 * t[len(t)//2:]) * np.exp(-10 * t[len(t)//2:])
            audio = np.concatenate([wave1, wave2])
        else:
            freq1, freq2 = 1200.0, 950.0
            wave1 = 0.35 * np.sin(2 * np.pi * freq1 * t[:len(t)//2]) * np.exp(-10 * t[:len(t)//2])
            wave2 = 0.25 * np.sin(2 * np.pi * freq2 * t[len(t)//2:]) * np.exp(-12 * t[len(t)//2:])
            audio = np.concatenate([wave1, wave2])
            
        audio = audio.astype(np.float32)
        return audio, sr_rate

    def play_chime(self, wake: bool = True):
        """Plays futuristic audio feedback."""
        try:
            data, fs = self._wake_chime if wake else self._confirm_chime
            sd.play(data, fs)
        except Exception as e:
            logger.debug(f"Erro ao tocar chime: {e}")

    def notify_state(self, state: str):
        """Notifies current assistant status (IDLE, LISTENING, PROCESSING, SPEAKING)."""
        if self.on_state_change:
            try:
                self.on_state_change(state)
            except Exception as e:
                logger.error(f"Erro no callback de estado: {e}")

    def speak(self, text: str, wait: bool = True):
        """Speaks text using natural edge-tts with pyttsx3 offline fallback."""
        if not text or not text.strip():
            return
            
        logger.info(f"JARVIS Falando: {text}")
        self.is_speaking = True
        self.notify_state("SPEAKING")
        
        # Audio file path
        filename = self.temp_dir / f"speech_{int(time.time()*1000)}.mp3"
        spoken_successfully = False
        
        # Try Edge-TTS (high quality neural voice)
        try:
            async def _synthesize():
                communicate = edge_tts.Communicate(
                    text=text,
                    voice=config.TTS_VOICE,
                    rate=config.TTS_RATE,
                    pitch=config.TTS_PITCH
                )
                await communicate.save(str(filename))
                
            asyncio.run(_synthesize())
            
            if filename.exists() and filename.stat().st_size > 0:
                data, fs = sf.read(str(filename))
                sd.play(data, fs)
                if wait:
                    sd.wait()
                spoken_successfully = True
        except Exception as e:
            logger.warning(f"Edge-TTS indisponível, usando fallback local: {e}")

        # Fallback to pyttsx3 if edge-tts failed
        if not spoken_successfully and self._pyttsx_engine:
            try:
                self._pyttsx_engine.say(text)
                self._pyttsx_engine.runAndWait()
                spoken_successfully = True
            except Exception as ex:
                logger.error(f"Erro no fallback pyttsx3: {ex}")

        # Clean up temporary audio file
        try:
            if filename.exists():
                filename.unlink(missing_ok=True)
        except Exception:
            pass
            
        self.is_speaking = False
        self.notify_state("IDLE")

    def record_phrase(self, samplerate: int = 16000, max_seconds: int = 10, silence_limit: float = 1.0) -> Optional[np.ndarray]:
        """
        Records microphone audio with dynamic Voice Activity Detection (VAD).
        Waits for voice and stops when silence is detected.
        """
        block_duration = 0.05  # 50ms blocks
        block_size = int(samplerate * block_duration)
        
        voice_started = False
        silence_start_time = None
        recorded_chunks = []
        start_time = time.time()
        
        energy_threshold = 0.015 # threshold for normalized float32 audio
        
        with sd.InputStream(samplerate=samplerate, channels=1, dtype='float32', blocksize=block_size) as stream:
            while not self.should_stop:
                if self.is_speaking:
                    # Do not listen while JARVIS is speaking to avoid self-triggering
                    time.sleep(0.1)
                    continue

                chunk, overflowed = stream.read(block_size)
                rms = np.sqrt(np.mean(chunk**2))
                
                # Report volume level for HUD animation
                if self.on_audio_level:
                    norm_level = min(1.0, float(rms * 10))
                    self.on_audio_level(norm_level)
                
                # Check voice activity
                if rms > energy_threshold:
                    if not voice_started:
                        voice_started = True
                    silence_start_time = None
                    recorded_chunks.append(chunk.copy())
                else:
                    if voice_started:
                        recorded_chunks.append(chunk.copy())
                        if silence_start_time is None:
                            silence_start_time = time.time()
                        elif time.time() - silence_start_time > silence_limit:
                            # Silence reached after speech
                            break
                    else:
                        # Keep a small buffer before speech begins (last 200ms)
                        if len(recorded_chunks) > 4:
                            recorded_chunks.pop(0)
                        recorded_chunks.append(chunk.copy())

                # Max timeout protection
                if voice_started and (time.time() - start_time > max_seconds):
                    break
                elif not voice_started and (time.time() - start_time > 30):
                    # No voice detected in 30 seconds
                    return None

        if not recorded_chunks or not voice_started:
            return None

        audio_full = np.concatenate(recorded_chunks, axis=0)
        return audio_full

    def transcribe_audio(self, audio_data: np.ndarray, samplerate: int = 16000) -> Optional[str]:
        """Transcribes recorded audio to text via Google Speech API with Whisper fallback."""
        if audio_data is None or len(audio_data) == 0:
            return None

        try:
            # Convert float32 [-1.0, 1.0] to int16 PCM bytes
            audio_int16 = (np.clip(audio_data, -1.0, 1.0) * 32767).astype(np.int16)
            byte_io = io.BytesIO()
            with sf.SoundFile(byte_io, mode='w', samplerate=samplerate, channels=1, format='WAV', subtype='PCM_16') as f:
                f.write(audio_int16)
            byte_io.seek(0)
            
            # Read via SpeechRecognition
            with sr.AudioFile(byte_io) as source:
                sr_audio = self._recognizer.record(source)

            # Transcribe via Google STT (free, high speed, Brazilian Portuguese)
            text = self._recognizer.recognize_google(sr_audio, language=config.STT_LANGUAGE)
            if text:
                logger.info(f"Reconhecido (Google STT): {text}")
                return text.strip()
        except sr.UnknownValueError:
            return None
        except sr.RequestError as e:
            logger.warning(f"Erro na API Google STT: {e}. Tentando fallback local...")
        except Exception as e:
            logger.error(f"Erro ao processar áudio: {e}")

        # Local fallback via faster-whisper if available
        try:
            from faster_whisper import WhisperModel
            # Using tiny model to be extremely light on RAM and disk
            model = WhisperModel("tiny", device="cpu", compute_type="int8")
            segments, info = model.transcribe(audio_data.flatten(), language="pt")
            text = " ".join([seg.text for seg in segments]).strip()
            if text:
                logger.info(f"Reconhecido (Whisper Tiny): {text}")
                return text
        except Exception as ex:
            logger.debug(f"Whisper fallback não disponível: {ex}")

        return None

    def listen_and_transcribe(self) -> Optional[str]:
        """Listens to microphone until a phrase is spoken and transcribes it."""
        self.notify_state("LISTENING")
        audio = self.record_phrase()
        if audio is None:
            self.notify_state("IDLE")
            return None

        self.notify_state("PROCESSING")
        text = self.transcribe_audio(audio)
        self.notify_state("IDLE")
        return text

audio_manager = AudioManager()
