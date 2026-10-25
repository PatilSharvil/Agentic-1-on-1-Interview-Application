import io
import wave
from pathlib import Path

import numpy as np

from app.audio import prepare_audio

ROOT = Path(__file__).resolve().parent.parent


def _wav(samples: np.ndarray, sr: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def test_silence_is_rejected():
    result = prepare_audio(_wav(np.zeros(16000 * 5)), ".wav")
    assert not result.ok
    assert result.reason == "silence"


def test_steady_tone_is_rejected_as_tonal():
    t = np.arange(16000 * 5) / 16000
    result = prepare_audio(_wav(0.3 * np.sin(2 * np.pi * 440 * t)), ".wav")
    assert not result.ok
    assert result.reason == "tonal_noise"


def test_low_level_hum_is_rejected():
    t = np.arange(16000 * 5) / 16000
    result = prepare_audio(_wav(0.02 * np.sin(2 * np.pi * 60 * t)), ".wav")
    assert not result.ok


def test_broadband_noise_is_rejected():
    rng = np.random.default_rng(3)
    result = prepare_audio(_wav(rng.standard_normal(16000 * 5) * 0.01), ".wav")
    assert not result.ok


def test_real_speech_is_accepted_and_trimmed():
    data = (ROOT / "frontend" / "public" / "test.wav").read_bytes()
    result = prepare_audio(data, ".wav")
    assert result.ok, result.reason
    assert result.wav is not None
    assert result.speech_ms >= 300
    assert result.duration_ms > 0
    assert result.wav[:4] == b"RIFF"


def test_very_short_clip_is_rejected():
    result = prepare_audio(_wav(np.zeros(1000)), ".wav")
    assert not result.ok


def test_garbage_bytes_do_not_raise():
    result = prepare_audio(b"not audio at all", ".webm")
    assert not result.ok
