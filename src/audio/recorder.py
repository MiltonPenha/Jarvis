from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import sounddevice as sd
import soundfile as sf

from config.settings import (
    AUDIO_CHANNELS,
    AUDIO_DTYPE,
    AUDIO_SAMPLE_RATE,
    DEFAULT_RECORD_SECONDS,
    CACHE_DIR,
)
from utils.logger import log


def ensure_audio_cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def list_audio_devices() -> None:
    log("Listando dispositivos de áudio...")
    devices = sd.query_devices()

    for index, device in enumerate(devices):
        max_input = device.get("max_input_channels", 0)
        max_output = device.get("max_output_channels", 0)
        default_sr = device.get("default_samplerate", "N/A")

        print(
            f"[{index}] {device['name']} | "
            f"input={max_input} output={max_output} sample_rate={default_sr}"
        )


def get_default_input_device() -> Optional[int]:
    default_devices = sd.default.device

    if isinstance(default_devices, (list, tuple)) and len(default_devices) >= 1:
        input_device = default_devices[0]
        if input_device is not None and input_device >= 0:
            return int(input_device)

    return None


def record_audio(
    duration_seconds: int = DEFAULT_RECORD_SECONDS,
    output_path: Optional[Path] = None,
) -> Path:
    ensure_audio_cache_dir()

    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = CACHE_DIR / f"recording_{timestamp}.wav"

    input_device = get_default_input_device()
    log(f"Dispositivo de entrada padrão: {input_device}")

    frames = int(duration_seconds * AUDIO_SAMPLE_RATE)

    log(
        f"Iniciando gravação por {duration_seconds}s "
        f"({AUDIO_SAMPLE_RATE} Hz, {AUDIO_CHANNELS} canal/canais)..."
    )

    audio = sd.rec(
        frames,
        samplerate=AUDIO_SAMPLE_RATE,
        channels=AUDIO_CHANNELS,
        dtype=AUDIO_DTYPE,
        device=input_device,
    )
    sd.wait()

    sf.write(str(output_path), audio, AUDIO_SAMPLE_RATE)
    log(f"Áudio salvo em: {output_path}")

    return output_path