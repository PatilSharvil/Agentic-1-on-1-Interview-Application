"""Audio pre-processing that makes Whisper reliable.

The single biggest source of Whisper "hallucinations" is sending silence,
background hum, or a chunk with no actual speech. Whisper is trained to always
emit *something*, so it invents phrases ("Thank you.", "I'm not sure what I'm
doing.") on noise.

This module:
  1. decodes any browser format to 16 kHz mono PCM (ffmpeg, with a WAV fast path),
  2. runs an adaptive energy VAD plus a tonality check,
  3. trims the clip to the spoken region with padding,
  4. rejects clips that contain too little speech,
  5. optionally applies mild gain for quiet microphones.

`prepare_audio` returns `ok=False` for anything that should never reach the
transcription API.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TARGET_RATE = 16000
FRAME_MS = 20.0
_DEEP_FILTER = Path(__file__).resolve().parent.parent / "bin" / "deep-filter.exe"
_RNNOISE_MODEL = Path(__file__).resolve().parent.parent / "models" / "rnnoise" / "bd.rnnn"


@dataclass
class PreparedAudio:
    ok: bool
    reason: str = ""
    wav: bytes | None = None
    sample_rate: int = TARGET_RATE
    duration_ms: int = 0
    speech_ms: int = 0
    snr_db: float = 0.0
    peak: float = 0.0
    speech_ratio: float = 0.0
    tonal: bool = False


def encode_wav(samples: np.ndarray, sample_rate: int = TARGET_RATE) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _decode_wav(data: bytes) -> tuple[np.ndarray, int] | None:
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            if w.getsampwidth() != 2:
                return None
            channels = w.getnchannels()
            sr = w.getframerate()
            raw = w.readframes(w.getnframes())
        pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        if channels > 1:
            pcm = pcm.reshape(-1, channels).mean(axis=1)
        return pcm, sr
    except Exception:
        return None


def _decode_ffmpeg(data: bytes) -> tuple[np.ndarray, int]:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not available")
    proc = subprocess.run(
        [
            exe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(TARGET_RATE),
            "pipe:1",
        ],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=25,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError((proc.stderr or b"ffmpeg decode failed").decode("utf-8", "ignore")[:200])
    pcm = np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0
    return pcm, TARGET_RATE


def decode_audio(data: bytes, suffix: str = ".wav") -> tuple[np.ndarray, int]:
    if not data:
        raise ValueError("empty audio")
    if suffix.lower().split("?")[0] in (".wav", ".wave"):
        decoded = _decode_wav(data)
        if decoded is not None and decoded[0].size:
            return decoded
    return _decode_ffmpeg(data)


def _resample(samples: np.ndarray, sr: int, target: int = TARGET_RATE) -> np.ndarray:
    if sr == target or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    n_out = int(round(samples.size * target / sr))
    x_old = np.arange(samples.size, dtype=np.float64)
    x_new = np.linspace(0.0, samples.size - 1, n_out)
    return np.interp(x_new, x_old, samples).astype(np.float32)


def _highpass(samples: np.ndarray, sr: int, cutoff_hz: float = 80.0) -> np.ndarray:
    """Remove DC, mains hum and desk rumble without touching speech band."""
    if cutoff_hz <= 0 or samples.size == 0 or cutoff_hz >= sr / 2:
        return samples
    try:
        from scipy.signal import butter, sosfilt

        sos = butter(2, cutoff_hz, btype="highpass", fs=sr, output="sos")
        return sosfilt(sos, samples).astype(np.float32)
    except Exception:
        return samples


def _read_wav_bytes(path: str) -> tuple[np.ndarray, int] | None:
    try:
        with open(path, "rb") as f:
            return _decode_wav(f.read())
    except Exception:
        return None


def _deepfilter_samples(samples: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
    """DeepFilterNet3 (MIT). Best open-source real-time denoiser we can ship."""
    if not _DEEP_FILTER.exists():
        return samples, sr
    try:
        with tempfile.TemporaryDirectory(prefix="df-") as td:
            src = os.path.join(td, "in.wav")
            outdir = os.path.join(td, "out")
            with open(src, "wb") as f:
                f.write(encode_wav(samples, sr))
            os.makedirs(outdir, exist_ok=True)
            proc = subprocess.run(
                [str(_DEEP_FILTER), "-o", outdir, src],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=25,
            )
            if proc.returncode != 0:
                return samples, sr
            decoded = _read_wav_bytes(os.path.join(outdir, "in.wav"))
            if decoded and decoded[0].size:
                return decoded
    except Exception:
        pass
    return samples, sr


def _rnnoise_samples(samples: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
    """RNNoise via ffmpeg's `arnndn` filter (BSD). Kept as a lighter fallback."""
    exe = shutil.which("ffmpeg")
    if not exe or not _RNNOISE_MODEL.exists():
        return samples, sr
    try:
        with tempfile.TemporaryDirectory(prefix="rnn-") as td:
            src = os.path.join(td, "in.wav")
            dst = os.path.join(td, "out.wav")
            with open(src, "wb") as f:
                f.write(encode_wav(samples, sr))
            proc = subprocess.run(
                [
                    exe, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", src, "-af", "arnndn=m=bd.rnnn",
                    "-ar", str(sr), "-ac", "1", dst,
                ],
                cwd=str(_RNNOISE_MODEL.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=25,
            )
            if proc.returncode != 0:
                return samples, sr
            decoded = _read_wav_bytes(dst)
            if decoded and decoded[0].size:
                return decoded
    except Exception:
        pass
    return samples, sr


def _snr_estimate_db(samples: np.ndarray, sr: int) -> float:
    db = _frame_rms_db(samples, sr)
    if db.size == 0:
        return 0.0
    noise = float(np.percentile(db, 15))
    speech = float(np.percentile(db, 90))
    return max(0.0, speech - noise)


def _maybe_denoise(samples: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
    """Apply the configured denoiser only to genuinely noisy chunks.

    Always running a denoiser costs latency and can distort clean speech, so we
    gate it on the estimated SNR. Clean studio/mic audio is left untouched.
    """
    from app.config import settings

    mode = (settings.stt_denoise or "off").strip().lower()
    if mode == "off" or samples.size == 0:
        return samples, sr
    if _snr_estimate_db(samples, sr) >= settings.stt_denoise_below_snr_db:
        return samples, sr
    if mode == "deepfilter":
        return _deepfilter_samples(samples, sr)
    if mode == "rnnoise":
        return _rnnoise_samples(samples, sr)
    return samples, sr


def _frame_rms_db(samples: np.ndarray, sr: int, frame_ms: float = FRAME_MS) -> np.ndarray:
    frame = max(1, int(sr * frame_ms / 1000))
    n = samples.size // frame
    if n == 0:
        return np.array([], dtype=np.float32)
    frames = samples[: n * frame].reshape(n, frame)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-7)).astype(np.float32)


def _merge_regions(active: np.ndarray, frame_ms: float, max_gap_ms: float, pad_ms: float) -> list[tuple[int, int]]:
    idx = np.flatnonzero(active)
    if idx.size == 0:
        return []
    regions: list[tuple[int, int]] = []
    start = prev = int(idx[0])
    max_gap = int(max_gap_ms / frame_ms)
    for i in idx[1:]:
        i = int(i)
        if i - prev <= max_gap:
            prev = i
            continue
        regions.append((start, prev))
        start = prev = i
    regions.append((start, prev))
    pad = int(pad_ms / frame_ms)
    padded = [(max(0, a - pad), b + pad) for a, b in regions]
    # merge after padding as well
    merged: list[list[int]] = []
    for a, b in padded:
        if merged and a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def _tonality(samples: np.ndarray, sr: int, frame_idx: np.ndarray, frame: int) -> tuple[float, float]:
    """Return (strongest-bin energy share, zero-crossing-rate std).

    A pure tone/hum has a high energy share *and* an almost constant ZCR.
    Speech has both harmonics (low share) and rapidly changing ZCR.
    """
    if frame_idx.size == 0:
        return 0.0, 0.0
    picks = frame_idx[:80]
    shares: list[float] = []
    zcrs: list[float] = []
    window = np.hanning(frame)
    for i in picks:
        chunk = samples[int(i) * frame : (int(i) + 1) * frame]
        if chunk.size < frame:
            continue
        spec = np.abs(np.fft.rfft(chunk * window)) ** 2
        total = float(spec.sum())
        if total <= 1e-12:
            continue
        shares.append(float(spec.max()) / total)
        zcrs.append(float(np.mean(np.abs(np.diff(np.signbit(chunk).astype(np.int8))))))
    if not shares:
        return 0.0, 0.0
    return float(np.mean(shares)), float(np.std(zcrs))


def prepare_audio(data: bytes, suffix: str = ".webm", min_speech_ms: int | None = None) -> PreparedAudio:
    from app.config import settings

    min_speech_ms = settings.stt_min_speech_ms if min_speech_ms is None else min_speech_ms
    try:
        samples, sr = decode_audio(data, suffix)
    except Exception as e:
        return PreparedAudio(ok=False, reason=f"decode_failed: {e}")

    if samples.size < int(sr * 0.15):
        return PreparedAudio(ok=False, reason="too_short")

    samples = _highpass(samples, sr, settings.stt_highpass_hz)
    samples, sr = _maybe_denoise(samples, sr)

    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak < 1e-4:
        return PreparedAudio(ok=False, reason="silence", peak=peak)

    db = _frame_rms_db(samples, sr)
    if db.size == 0:
        return PreparedAudio(ok=False, reason="too_short")

    # Adaptive threshold: a little above the room's noise floor, and never so
    # low that dither/DC offset counts as speech.
    noise_db = float(np.percentile(db, 15))
    noise_db = min(noise_db, -38.0)
    threshold_db = max(noise_db + 9.0, -47.0)
    active = db > threshold_db

    frame_ms = FRAME_MS
    regions = _merge_regions(active, frame_ms, max_gap_ms=380.0, pad_ms=180.0)
    if not regions:
        return PreparedAudio(ok=False, reason="no_speech", peak=peak)

    frame = max(1, int(sr * frame_ms / 1000))
    active_frames = np.flatnonzero(active)
    speech_ms = int(round(active_frames.size * frame_ms))
    if speech_ms < min_speech_ms:
        return PreparedAudio(ok=False, reason="speech_too_short", peak=peak, speech_ms=speech_ms)

    # Reject steady tones / hum: Whisper turns them into phantom words.
    concentration, zcr_std = _tonality(samples, sr, active_frames, frame)
    tonal = zcr_std < 0.035 or (concentration > 0.55 and zcr_std < 0.06)
    if tonal:
        return PreparedAudio(
            ok=False,
            reason="tonal_noise",
            peak=peak,
            speech_ms=speech_ms,
            tonal=True,
        )

    start = int(regions[0][0] * frame)
    end = min(samples.size, int(regions[-1][1] * frame))
    trimmed = samples[start:end]

    # Keep at least 200 ms of context on both sides.
    pre = int(sr * 0.20)
    post = int(sr * 0.25)
    start2 = max(0, start - pre)
    end2 = min(samples.size, end + post)
    trimmed = samples[start2:end2]

    # Quiet mic: gentle, bounded gain (never amplify a noisy floor).
    noise_rms = max(10.0 ** (noise_db / 20.0), 1e-6)
    speech_rms = float(np.sqrt(np.mean(trimmed.astype(np.float64) ** 2) + 1e-12))
    snr_db = 20.0 * np.log10(max(speech_rms, 1e-7) / noise_rms)
    trimmed_peak = float(np.max(np.abs(trimmed))) if trimmed.size else 0.0
    if 0 < trimmed_peak < 0.35 and snr_db > 12.0:
        gain = min(0.6 / trimmed_peak, 4.0)
        trimmed = np.clip(trimmed * gain, -1.0, 1.0)
        speech_rms *= gain

    trimmed = _resample(trimmed, sr)
    duration_ms = int(round(trimmed.size * 1000 / TARGET_RATE))
    return PreparedAudio(
        ok=True,
        reason="ok",
        wav=encode_wav(trimmed, TARGET_RATE),
        sample_rate=TARGET_RATE,
        duration_ms=duration_ms,
        speech_ms=speech_ms,
        snr_db=round(float(snr_db), 1),
        peak=round(float(np.max(np.abs(trimmed))) if trimmed.size else 0.0, 3),
        speech_ratio=round(speech_ms / max(duration_ms, 1), 2),
        tonal=False,
    )
