"""Local neural voice. Load prepared assets once; never download during synthesis."""
import json
import threading
import tempfile
import wave
from pathlib import Path
from core.config import config

class NeuralVoice:
    def __init__(self):
        self._voice=None
        self._load_lock=threading.Lock()
        self._synthesis_lock=threading.Lock()

    @property
    def ready(self):
        return self._voice is not None

    def prepare(self):
        with self._load_lock:
            if self._voice is None:
                path=config.PIPER_MODEL_PATH
                metadata=path.with_suffix(path.suffix+'.json')
                if not path.is_file() or not metadata.is_file():
                    raise ValueError('Voz neural local não preparada. Execute scripts/setup_voice.ps1.')
                import onnxruntime as ort
                from piper import PiperVoice,PiperConfig
                options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
                session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
                self._voice=PiperVoice(session=session,config=PiperConfig.from_dict(json.loads(metadata.read_text(encoding='utf-8'))),
                                       download_dir=path.parent)
        return self._voice

    def synthesize(self,text,path,profile=None):
        from piper import SynthesisConfig
        voice=self.prepare()
        if profile not in (None,'original','natural'):raise ValueError('Perfil Piper inválido.')
        profile=SynthesisConfig(length_scale=1.0 if profile=='natural' else config.PIPER_LENGTH_SCALE,noise_scale=.62,noise_w_scale=.75,
                                normalize_audio=True,volume=.92)
        with self._synthesis_lock,wave.open(str(path),'wb') as output:
            voice.synthesize_wav(text,output,syn_config=profile)

    def warmup(self):
        # Initializes the phonemizer and first inference without playing any sound.
        with tempfile.TemporaryDirectory(prefix='jarvis-voice-') as folder:
            self.synthesize('Senhor.',Path(folder)/'warmup.wav')

neural_voice=NeuralVoice()
