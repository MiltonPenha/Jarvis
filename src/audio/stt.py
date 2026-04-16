from __future__ import annotations

from pathlib import Path

from faster_whisper import WhisperModel

from config.settings import LANGUAGE
from utils.logger import log


_gpu_model = None
_cpu_model = None


def get_gpu_model() -> WhisperModel:
    global _gpu_model

    if _gpu_model is None:
        log("Loading Whisper model with CUDA...")
        _gpu_model = WhisperModel(
            "base",
            device="cuda",
            compute_type="float16",
        )

    return _gpu_model


def get_cpu_model() -> WhisperModel:
    global _cpu_model

    if _cpu_model is None:
        log("Loading Whisper model with CPU...")
        _cpu_model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8",
        )

    return _cpu_model


def _run_transcription(model: WhisperModel, audio_path: Path) -> str:
    segments, info = model.transcribe(
        str(audio_path),
        language=LANGUAGE,
    )

    text_parts = [segment.text.strip() for segment in segments if segment.text.strip()]
    text = " ".join(text_parts).strip()

    log(
        f"Transcription finished | language={info.language} "
        f"probability={info.language_probability:.2f}"
    )
    log(f"Recognized text: {text}")

    return text


def transcribe_audio(audio_path: Path) -> str:
    log(f"Starting transcription: {audio_path}")

    try:
        log("Trying GPU transcription...")
        gpu_model = get_gpu_model()
        return _run_transcription(gpu_model, audio_path)

    except Exception as exc:
        log(f"GPU transcription failed: {exc}")
        log("Falling back to CPU transcription...")

        cpu_model = get_cpu_model()
        return _run_transcription(cpu_model, audio_path)