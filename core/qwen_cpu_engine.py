"""CPU-only Qwen engine, imported exclusively inside its isolated voice worker."""
import hashlib
import os
from pathlib import Path
import sys

SOURCE_SHA256 = '28d2a4ddcda8bbae6ab58b75ebf429541e366a1f50a583a9f8ac1cf58e80c167'
REFERENCE_SHA256 = 'f093e7595f0c9085b914469145bc2edf521cfa0aa22866d926fe67dd577f6081'
REFERENCE_TEXT_SHA256 = '65c471ef56a8def97240fa733107f962a88229591e23e06a3d29ada29f48af10'


class QwenCpuEngine:
    def __init__(self, home, threads=8):
        self.home = Path(home)
        for name, expected in (('inference.py', SOURCE_SHA256), ('reference.wav', REFERENCE_SHA256),
                               ('reference-short-text.txt', REFERENCE_TEXT_SHA256)):
            path = self.home/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Arquivos de voz Qwen ausentes ou diferentes da referência preparada.')
        os.environ.update(CUDA_VISIBLE_DEVICES='-1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
            USE_TORCH='0', TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS=str(threads),
            OPENBLAS_NUM_THREADS=str(threads), MKL_NUM_THREADS=str(threads))
        sys.path[:0] = [str(self.home/'packages'), str(self.home)]
        import onnxruntime as ort
        original = ort.InferenceSession
        self.sessions = []
        def cpu_session(path, *args, **kwargs):
            options = ort.SessionOptions()
            options.intra_op_num_threads = threads
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            options.add_session_config_entry('session.intra_op.allow_spinning', '0')
            options.add_session_config_entry('session.inter_op.allow_spinning', '0')
            options.enable_cpu_mem_arena = False
            options.enable_mem_pattern = False
            options.log_severity_level = 3
            session = original(path, sess_options=options, providers=['CPUExecutionProvider'])
            if session.get_providers() != ['CPUExecutionProvider']:
                raise RuntimeError('O motor de voz exige execução somente na CPU.')
            self.sessions.append(session)
            return session
        # This patch is contained in the dedicated process, never in the HUD/server.
        ort.InferenceSession = cpu_session
        from inference import Pipeline
        from transformers import AutoTokenizer
        self.pipe = Pipeline(str(self.home/'model'), tts_dir=str(self.home/'model'))
        self.pipe._tok = AutoTokenizer.from_pretrained(str(self.home/'model'), local_files_only=True,
            trust_remote_code=False, fix_mistral_regex=False)
        self.ref_text = (self.home/'reference-short-text.txt').read_text(encoding='utf-8')
        self.ref_path = str(self.home/'reference.wav')
        wav = self.pipe._load_ref_wav(self.ref_path)
        ref_codes = self.pipe.encode_chunked(wav)
        speaker = self.pipe.speaker_encoder.run(None, {'audio': wav[None]})[0]
        class FixedSpeaker:
            def run(self, *args, **kwargs):
                return [speaker.copy()]
        self.pipe.speaker_encoder = FixedSpeaker()
        self.pipe.encode_chunked = lambda audio: ref_codes.copy()

    def synthesize(self, text, path):
        import numpy as np
        import soundfile as sf
        codes = self.pipe.generate(text, language='Portuguese', ref_audio=self.ref_path,
            ref_text=self.ref_text, max_new_tokens=384, seed=42, verbose=False)
        if len(codes) == 0 or len(codes) >= 384:
            raise ValueError('A síntese Qwen terminou sem uma frase completa. Tente uma resposta mais curta.')
        wav = self.pipe.decode_chunked(codes[None]).reshape(-1)
        if not len(wav) or not np.isfinite(wav).all():
            raise ValueError('A síntese Qwen não retornou áudio válido.')
        sf.write(str(path), wav, 24000)
