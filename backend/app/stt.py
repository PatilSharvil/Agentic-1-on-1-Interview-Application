import os
import tempfile
from typing import Callable, Protocol

from app.config import settings


class STTService(Protocol):
    def transcribe_bytes(self, audio_bytes: bytes, suffix: str = ".webm", prompt: str | None = None) -> str: ...


class GroqSTT:
    def __init__(self, model: str | None = None):
        from groq import Groq

        api_key = settings.groq_api_key or os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set (put it in .env)")
        self.client = Groq(api_key=api_key)
        self.model = model or settings.stt_model

    def transcribe_bytes(self, audio_bytes: bytes, suffix: str = ".webm", prompt: str | None = None) -> str:
        kwargs = {
            "file": (f"audio{suffix}", audio_bytes),
            "model": self.model,
            "response_format": "text",
            "language": "en",
            "temperature": 0.0,
        }
        if prompt or settings.stt_prompt:
            kwargs["prompt"] = prompt or settings.stt_prompt
        transcription = self.client.audio.transcriptions.create(**kwargs)
        if isinstance(transcription, str):
            return transcription.strip()
        return (getattr(transcription, "text", "") or "").strip()


class FasterWhisperSTT:
    def __init__(self, model: str | None = None):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(model or "base", device="cpu", compute_type="int8")

    def transcribe_bytes(self, audio_bytes: bytes, suffix: str = ".webm", prompt: str | None = None) -> str:
        fd, path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(audio_bytes)
            segments, _ = self.model.transcribe(path, language="en", condition_on_previous_text=False, no_speech_threshold=0.6, log_prob_threshold=-1.0, temperature=0.0)
            return " ".join(s.text.strip() for s in segments).strip()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


class ChainSTT:
    """Tries providers in order; the first one that succeeds becomes the active provider."""

    def __init__(self, factories: list[Callable[[], STTService]]):
        self.factories = factories
        self.active: STTService | None = None

    def transcribe_bytes(self, audio_bytes: bytes, suffix: str = ".webm", prompt: str | None = None) -> str:
        if self.active is not None:
            try:
                return self.active.transcribe_bytes(audio_bytes, suffix, prompt)
            except Exception:
                self.active = None

        errors = []
        for factory in self.factories:
            try:
                svc = factory()
                text = svc.transcribe_bytes(audio_bytes, suffix, prompt)
                self.active = svc
                return text
            except Exception as e:
                errors.append(f"{factory.__name__}: {e}")
        raise RuntimeError("all STT providers failed -> " + " | ".join(errors))


_stt_instance: STTService | None = None


def get_stt() -> STTService:
    global _stt_instance
    if _stt_instance is None:
        if settings.stt_provider == "faster-whisper":
            _stt_instance = FasterWhisperSTT()
        elif settings.stt_provider == "groq":
            _stt_instance = ChainSTT(
                [
                    lambda: GroqSTT(settings.stt_model),
                    lambda: GroqSTT(settings.stt_fallback_model),
                    lambda: FasterWhisperSTT(),
                ]
            )
        else:
            raise ValueError(f"unknown stt provider: {settings.stt_provider}")
    return _stt_instance


_HALLUCINATIONS = {
    "i'm not sure what i'm doing",
    "i'm not sure what i am doing",
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "like and subscribe",
    "you",
    ".",
    "",
}

def _is_hallucination(text: str) -> bool:
    t = text.strip().lower().rstrip(".!,")
    if t in _HALLUCINATIONS:
        return True
    # repeated same phrase
    words = t.split()
    if len(words) >= 4 and len(set(words)) <= 2:
        return True
    return False

def clean_transcript(raw: str) -> str:
    """Use a fast LLM to clean up raw STT output: fix grammar, remove filler words, correct misheard terms."""
    if not raw or not raw.strip():
        return ""
    if _is_hallucination(raw):
        return ""
    try:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "You clean up speech-to-text transcripts. Fix grammar, remove filler words (um, uh, like, you know), correct obvious misheard technical terms. Keep the original meaning. Output ONLY the cleaned text, nothing else.",
                },
                {"role": "user", "content": raw},
            ],
            temperature=0.1,
            max_tokens=512,
        )
        cleaned = (resp.choices[0].message.content or "").strip()
        return cleaned if cleaned else raw
    except Exception as e:
        print(f"[stt] LLM clean failed: {e}")
        return raw