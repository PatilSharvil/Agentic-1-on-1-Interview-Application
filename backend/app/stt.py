"""Speech-to-text with hallucination guards.

Pipeline for every chunk:
    bytes -> audio.prepare_audio (VAD + trim) -> Groq Whisper verbose_json
          -> per-segment confidence filtering -> text-level hallucination checks
          -> optional verification with whisper-large-v3
          -> deterministic cleanup (+ guarded LLM polish)

`prepare_audio` is the primary defence: silence, hum and noise never reach the
API. Segment/text filters catch whatever still slips through.
"""
from __future__ import annotations

import os
import re
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Protocol

from app.audio import prepare_audio
from app.config import settings
from app.llm import chat_sync


@dataclass
class STTResult:
    text: str = ""
    raw: str = ""
    status: str = "ok"  # ok | no_speech | hallucination | error
    reason: str = ""
    model: str = ""
    duration_ms: int = 0
    speech_ms: int = 0
    snr_db: float = 0.0
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    latency_ms: int = 0
    segments: list[dict] = field(default_factory=list)


class STTService(Protocol):
    def transcribe_detailed(self, audio_bytes: bytes, suffix: str = ".webm", prompt: str | None = None) -> STTResult: ...

    def transcribe_bytes(self, audio_bytes: bytes, suffix: str = ".webm", prompt: str | None = None) -> str: ...


# --------------------------------------------------------------------------- #
# Text-level hallucination detection
# --------------------------------------------------------------------------- #

_HALLUCINATION_PHRASES = {
    "thank you for watching",
    "thanks for watching",
    "thank you for watching!",
    "please subscribe",
    "like and subscribe",
    "subscribe to my channel",
    "subtitles by",
    "amara org",
    "i'm not sure what i'm doing",
    "i am not sure what i am doing",
    "i'm not sure what i'm doing.",
    "you",
    "bye",
    "thank you",
    "thanks",
    "and more",
    "technical terms",
    "technical term",
    "hmm",
    "mm",
    "uh",
    "um",
    "the",
    "a",
}

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "to", "of", "in", "on", "at", "for",
    "with", "from", "by", "as", "is", "are", "was", "were", "be", "been", "being", "am", "i", "you",
    "he", "she", "it", "we", "they", "my", "your", "our", "their", "this", "that", "these", "those",
    "have", "has", "had", "do", "does", "did", "will", "would", "can", "could", "should", "may",
    "might", "about", "into", "like", "just", "very", "really", "there", "here", "what", "which",
}

_FILLERS = {"um", "uh", "umm", "uhh", "erm", "er", "hmm", "hm", "mmm", "mm", "uhm", "ah", "ahh"}

_NOISE_ANNOTATIONS = re.compile(
    r"[\[\(\{]\s*(?:music|applause|laughter|laughs|inaudible|noise|silence|blank_audio|"
    r"background noise|clears throat|coughs?|sighs?)\s*[\]\)\}]",
    re.IGNORECASE,
)

# Safe canonical casing fixes. Only casing/spacing changes, never word swaps.
_GLOSSARY = {
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "java": "Java",
    "react": "React",
    "angular": "Angular",
    "vue": "Vue",
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "spring boot": "Spring Boot",
    "node.js": "Node.js",
    "nodejs": "Node.js",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "sql": "SQL",
    "nosql": "NoSQL",
    "redis": "Redis",
    "mongodb": "MongoDB",
    "graphql": "GraphQL",
    "api": "API",
    "apis": "APIs",
    "rest api": "REST API",
    "ci/cd": "CI/CD",
    "aws": "AWS",
    "gcp": "GCP",
    "azure": "Azure",
    "git": "Git",
    "github": "GitHub",
    "gitlab": "GitLab",
    "c++": "C++",
    "c#": "C#",
    "rust": "Rust",
    "terraform": "Terraform",
    "linux": "Linux",
    "nginx": "Nginx",
    "websocket": "WebSocket",
    "websockets": "WebSockets",
    "microservices": "microservices",
    "kubectl": "kubectl",
    "json": "JSON",
    "yaml": "YAML",
    "http": "HTTP",
    "https": "HTTPS",
    "websockets": "WebSockets",
}

_PHRASE_FIXES = {
    "fast api": "FastAPI",
    "java script": "JavaScript",
    "type script": "TypeScript",
    "node js": "Node.js",
    "my sql": "MySQL",
    "post gres": "PostgreSQL",
    "postgres sql": "PostgreSQL",
    "cube control": "kubectl",
    "k eight s": "Kubernetes",
    "kube earnets": "Kubernetes",
    "kubeearnets": "Kubernetes",
    "kubernetis": "Kubernetes",
    "kubernets": "Kubernetes",
    "cubernetis": "Kubernetes",
    "cuba or nets": "Kubernetes",
    "cuba nets": "Kubernetes",
    "teraform": "Terraform",
    "terra form": "Terraform",
    "ci cd": "CI/CD",
    "ci-cd": "CI/CD",
    "cicd": "CI/CD",
    "readies cache": "Redis cache",
    "redies cache": "Redis cache",
    "reddis cache": "Redis cache",
    "git hub": "GitHub",
    "graph ql": "GraphQL",
    "mongo db": "MongoDB",
    "web socket": "WebSocket",
    "micro services": "microservices",
    "pie thon": "Python",
    "re act": "React",
    "a w s": "AWS",
    "g c p": "GCP",
    "a p i": "API",
}

# Multi-word names that must not be normalised word-by-word.
_PROTECTED_SPANS = ["Spring Boot", "REST API", "CI/CD", "Node.js", "C++", "C#", "Node JS"]


def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _norm_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#./]+", _normalize(text).lower())


def _content_tokens(text: str) -> set[str]:
    return {t for t in _norm_tokens(text) if t not in _STOPWORDS and len(t) > 2}


def _ascii_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    return sum(1 for c in letters if ord(c) < 128) / len(letters)


_FOREIGN_STOPWORDS = {
    # French
    "je", "suis", "une", "et", "les", "des", "du", "est", "dans", "pour", "avec", "pas",
    "qui", "nous", "vous", "ils", "elles", "mon", "mais", "notre", "votre", "leur", "leurs",
    "sommes", "sont", "êtes", "bonjour", "merci", "ingénieur", "travail", "années", "expérience",
    # German
    "ich", "und", "der", "die", "das", "nicht", "ist", "mit", "auf", "ein", "eine", "bin",
    "bist", "sind", "habe", "hast", "haben", "mein", "meine", "sehr", "danke", "hallo",
    "ingenieur", "erfahrung", "arbeit",
    # Spanish
    "el", "los", "las", "para", "por", "con", "una", "soy", "eres", "está", "estoy", "hola",
    "gracias", "ingeniero", "trabajo", "años", "experiencia", "porque", "también", "pero",
    "sin", "del", "unos", "unas", "nuestro", "nuestra",
    # Italian
    "sono", "non", "che", "il", "lo", "per", "della", "ciao", "grazie", "ingegnere",
    "lavoro", "esperienza", "perché", "molto",
    # Portuguese
    "sou", "somos", "são", "tenho", "temos", "obrigado", "olá", "engenheiro", "trabalho",
    "experiência", "muito",
    # Hindi (romanised)
    "kya", "nahi", "nahin", "hai", "hain", "hoon", "aap", "mera", "meri", "hamara", "hamari",
    "tum", "raha", "rahi", "rahe", "bohot", "bahut", "acha", "accha", "karta", "karti", "karte",
    "hota", "hoti", "aur", "mujhe", "pasand", "bhi", "abhi", "kaam", "kuch", "yeh", "woh",
    "kaise", "kyun", "kyu", "theek", "thik",
}


def _looks_foreign(text: str) -> bool:
    words = re.findall(r"[^\W\d_]+", text.lower())
    if not words:
        return False
    hits = sum(1 for w in words if w in _FOREIGN_STOPWORDS)
    return hits >= 2 or (len(words) >= 3 and hits / len(words) >= 0.4)


def _is_repetition_loop(tokens: list[str]) -> bool:
    if len(tokens) < 6:
        return False
    # any 3-gram repeated three or more times
    trigrams: dict[tuple[str, ...], int] = {}
    for i in range(len(tokens) - 2):
        key = tuple(tokens[i : i + 3])
        trigrams[key] = trigrams.get(key, 0) + 1
        if trigrams[key] >= 3:
            return True
    # "word word word word word"
    if len(set(tokens)) <= 2 and len(tokens) >= 5:
        return True
    return False


def _prompt_echo(text: str, prompt: str | None) -> bool:
    if not prompt:
        return False
    tokens = _content_tokens(text)
    if not tokens:
        return False
    prompt_tokens = _content_tokens(prompt)
    if not prompt_tokens:
        return False
    overlap = tokens & prompt_tokens
    # short output made only of prompt words -> it is the prompt coming back
    if len(_norm_tokens(text)) <= 6 and overlap and len(overlap) / len(tokens) >= 0.8:
        return True
    # a long verbatim run from the prompt
    prompt_words = _norm_tokens(prompt)
    out_words = _norm_tokens(text)
    if len(prompt_words) >= 4:
        for size in range(min(8, len(out_words)), 3, -1):
            for i in range(len(out_words) - size + 1):
                needle = out_words[i : i + size]
                if any(prompt_words[j : j + size] == needle for j in range(len(prompt_words) - size + 1)):
                    return True
    return False


def base_prompt_for_echo() -> str | None:
    """Static base prompt only, for the echo guard.

    Dynamic continuation context (the previous utterance tail passed as prompt)
    is deliberately excluded: when speech continues across a chunk boundary the
    output legitimately repeats those words, and `remove_overlap` strips that
    repetition. The echo guard must not reject such continuations.
    """
    if not settings.stt_use_prompt:
        return None
    base = _normalize(settings.stt_prompt or "")
    return base or None


def is_hallucination(text: str, prompt: str | None = None, avg_logprob: float | None = None) -> bool:
    """Conservative text filter. Returns True when the text must be discarded."""
    t = _normalize(text)
    if not t:
        return True
    if not any(c.isalnum() for c in t):
        return True
    if _ascii_ratio(t) < 0.97:
        return True
    if _looks_foreign(t):
        return True

    low = t.lower().strip(" .,!?;:\"'")
    low = re.sub(r"\s+", " ", low)
    if low in _HALLUCINATION_PHRASES:
        return True

    tokens = _norm_tokens(t)
    if _is_repetition_loop(tokens):
        return True
    if _prompt_echo(t, prompt):
        return True
    # A single word with almost no letters is noise ("The", ".", "-")
    if len(tokens) == 1 and len(tokens[0]) < 3:
        return True
    if avg_logprob is not None and avg_logprob < settings.stt_logprob_threshold and len(tokens) <= 4:
        return True
    return False


# --------------------------------------------------------------------------- #
# Cross-chunk de-duplication
# --------------------------------------------------------------------------- #

def remove_overlap(previous: str, new: str) -> str:
    """Drop the repeated words Whisper emits on overlapping/rolling chunks."""
    if not new:
        return ""
    prev_tokens = _norm_tokens(previous)
    new_tokens = _norm_tokens(new)
    if not new_tokens:
        return ""
    if prev_tokens and new_tokens == prev_tokens:
        return ""
    if prev_tokens and len(new_tokens) <= 3:
        tail = prev_tokens[-len(new_tokens) :]
        if tail == new_tokens:
            return ""

    # map normalised token -> position in the original string, then cut the
    # matched prefix off the original text (preserves casing/punctuation).
    words = new.split()
    n = min(12, len(prev_tokens), len(new_tokens))
    for size in range(n, 0, -1):
        if prev_tokens[-size:] != new_tokens[:size]:
            continue
        if size == 1 and len(new_tokens[0]) < 3:
            continue
        # remove `size` tokens from the front of `words`
        removed = 0
        idx = 0
        while idx < len(words) and removed < size:
            idx += 1
            removed += len(_norm_tokens(words[idx - 1]))
        return " ".join(words[idx:]).strip()
    return new


# --------------------------------------------------------------------------- #
# Deterministic cleanup + guarded LLM polish
# --------------------------------------------------------------------------- #

def _collapse_repeats(text: str) -> str:
    # "I I I think" / "the the" (single short word repeated)
    text = re.sub(r"\b(\w{1,12})(?:\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)
    # "a a" -> "a"
    return text


def _apply_case_fixes(text: str) -> str:
    protected: dict[str, str] = {}

    def stash(match: re.Match) -> str:
        token = f"@@P{len(protected)}@@"
        protected[token] = match.group(0)
        return token

    # protect exact canonical spellings already present
    for span in _PROTECTED_SPANS:
        text = re.sub(rf"(?<![\w.]){re.escape(span)}(?![\w.])", stash, text)

    for phrase, canonical in sorted(_PHRASE_FIXES.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<![\w.]){re.escape(phrase)}(?!\w)", canonical, text, flags=re.IGNORECASE)

    def fix_word(match: re.Match) -> str:
        word = match.group(0)
        canonical = _GLOSSARY.get(word.lower())
        if canonical:
            return canonical
        return word

    text = re.sub(r"[A-Za-z][A-Za-z0-9+#./]*", fix_word, text)

    for token, original in protected.items():
        text = text.replace(token, original)
    return text


def clean_text_deterministic(text: str) -> str:
    t = _normalize(text)
    if not t:
        return ""
    t = _NOISE_ANNOTATIONS.sub(" ", t)
    t = re.sub(r"\s+", " ", t)

    # drop standalone filler words
    words = t.split()
    kept: list[str] = []
    for word in words:
        bare = re.sub(r"[^\w']", "", word).lower()
        if bare in _FILLERS:
            continue
        kept.append(word)
    t = " ".join(kept)

    t = _collapse_repeats(t)
    t = _apply_case_fixes(t)
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()

    # capitalise sentence starts
    def cap(match: re.Match) -> str:
        return match.group(1) + match.group(2).upper()

    t = re.sub(r"(^|[.!?]\s+)([a-z])", cap, t)
    t = re.sub(r"\bi\b", "I", t)

    if t and t[-1] not in ".!?":
        t += "."
    return t.strip()


_POLISH_SYSTEM = (
    "You are a precise transcript corrector. You fix punctuation, capitalisation and "
    "obvious speech-recognition errors only. You must NEVER add, remove, summarise or "
    "rephrase information. If you are not sure, copy the original wording. Output only "
    "the corrected transcript, with no quotes and no explanation."
)


def _polish_guard(raw: str, out: str) -> bool:
    raw_n = _normalize(raw)
    out_n = _normalize(out).strip('"').strip()
    if not out_n:
        return False
    if len(out_n) > 2000:
        return False
    # model commentary leaked in
    if re.match(r"(?i)^(here|sure|certainly|the corrected|corrected|cleaned|transcript)\b", out_n):
        return False
    if "\n" in out_n or "```" in out_n:
        return False
    raw_words = _norm_tokens(raw_n)
    out_words = _norm_tokens(out_n)
    if not raw_words or not out_words:
        return False
    ratio = len(out_words) / len(raw_words)
    if ratio < 0.6 or ratio > 1.5:
        return False
    raw_content = _content_tokens(raw_n)
    out_content = _content_tokens(out_n)
    if not out_content:
        return False
    union = raw_content | out_content
    jaccard = len(raw_content & out_content) / len(union) if union else 1.0
    if jaccard < 0.6:
        return False
    added = out_content - raw_content
    if len(added) > max(2, int(0.25 * len(raw_content))):
        return False
    raw_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", raw_n))
    if not set(re.findall(r"\b\d+(?:\.\d+)?\b", out_n)) <= raw_numbers:
        return False
    return True


def polish_text(text: str) -> str:
    if settings.stt_cleanup != "llm" or not text:
        return text
    word_count = len(text.split())
    prompt = f"Correct this transcript:\n\n{text}"
    try:
        out = chat_sync(
            prompt,
            system=_POLISH_SYSTEM,
            max_tokens=min(1024, word_count * 3 + 64),
            temperature=0.0,
        )
    except Exception as e:  # pragma: no cover - network dependent
        print(f"[stt] polish unavailable ({e}); using deterministic cleanup")
        return text
    out = _normalize(out).strip().strip('"')
    if not _polish_guard(text, out):
        print("[stt] polish rejected by guard, keeping deterministic text")
        return text
    return clean_text_deterministic(out)


def clean_transcript(raw: str) -> str:
    """Clean ASR output without changing its meaning."""
    if not raw or not raw.strip():
        return ""
    if settings.stt_cleanup == "off":
        return _normalize(raw)
    cleaned = clean_text_deterministic(raw)
    if not cleaned:
        return ""
    return polish_text(cleaned)


# --------------------------------------------------------------------------- #
# Groq Whisper
# --------------------------------------------------------------------------- #

class GroqSTT:
    def __init__(self, model: str | None = None):
        from groq import Groq

        api_key = settings.groq_api_key or os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set (put it in .env)")
        self.client = Groq(api_key=api_key, timeout=60.0, max_retries=1)
        self.model = model or settings.stt_model

    def _prompt(self, override: str | None) -> str | None:
        if not settings.stt_use_prompt:
            return None
        base = _normalize(settings.stt_prompt or "")
        extra = _normalize(override or "")
        prompt = " ".join(part for part in (base, extra) if part)
        if not prompt:
            return None
        words = prompt.split()
        if len(words) > settings.stt_prompt_max_words:
            prompt = " ".join(words[: settings.stt_prompt_max_words])
        return prompt

    def _request(self, wav: bytes, model: str, prompt: str | None) -> dict:
        kwargs = {
            "file": ("audio.wav", wav),
            "model": model,
            "response_format": "verbose_json",
            "language": settings.stt_language,
            "temperature": 0.0,
        }
        if prompt:
            kwargs["prompt"] = prompt
        resp = self.client.audio.transcriptions.create(**kwargs)
        data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        return data

    def _filter_segments(self, data: dict) -> tuple[str, list[dict], float | None, float | None]:
        segments = data.get("segments") or []
        kept: list[dict] = []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            nsp = float(seg.get("no_speech_prob") or 0.0)
            lp = float(seg.get("avg_logprob") or 0.0)
            cr = float(seg.get("compression_ratio") or 0.0)
            # hard rejects: near-certain non-speech or degenerate looping
            if nsp >= 0.75:
                continue
            if cr > settings.stt_compression_ratio_threshold:
                continue
            if lp < -1.4:
                continue
            kept.append({**seg, "text": text})

        if not kept:
            # fall back to the aggregate text only when segments were absent
            text = (data.get("text") or "").strip()
            return text, [], None, None

        text = " ".join(s["text"] for s in kept).strip()
        dur = sum(max(0.0, float(s.get("end", 0)) - float(s.get("start", 0))) for s in kept) or 1.0
        avg_lp = sum(float(s.get("avg_logprob") or 0.0) * max(0.001, float(s.get("end", 0)) - float(s.get("start", 0))) for s in kept) / dur
        max_nsp = max(float(s.get("no_speech_prob") or 0.0) for s in kept)
        return text, kept, avg_lp, max_nsp

    def _attempt(self, prepared, model: str, prompt: str | None,
                 echo_prompt: str | None = None) -> STTResult:
        started = time.time()
        data = self._request(prepared.wav, model, prompt)
        text, segments, avg_lp, nsp = self._filter_segments(data)
        latency = int((time.time() - started) * 1000)
        suspicious = (avg_lp is not None and avg_lp < -0.9) or (nsp is not None and nsp > 0.4)
        result = STTResult(
            text="",
            raw=_normalize(text),
            status="ok",
            model=model,
            duration_ms=prepared.duration_ms,
            speech_ms=prepared.speech_ms,
            snr_db=prepared.snr_db,
            avg_logprob=round(avg_lp, 3) if avg_lp is not None else None,
            no_speech_prob=round(nsp, 3) if nsp is not None else None,
            latency_ms=latency,
            segments=segments,
        )
        if not text or is_hallucination(text, echo_prompt if echo_prompt is not None else prompt, avg_lp):
            result.status = "hallucination"
            result.reason = "segment_filter" if not text else "text_filter"
            return result
        # This app is English-only: discard anything Whisper labels as another language.
        lang = str(data.get("language") or "").strip().lower()
        if lang and not lang.startswith("en"):
            result.status = "hallucination"
            result.reason = "non_english"
            return result
        if suspicious:
            result.reason = "low_confidence"
        result.text = text
        return result

    def transcribe_detailed(self, audio_bytes: bytes, suffix: str = ".webm", prompt: str | None = None) -> STTResult:
        prepared = prepare_audio(audio_bytes, suffix)
        if not prepared.ok:
            return STTResult(status="no_speech", reason=prepared.reason, duration_ms=prepared.duration_ms, speech_ms=prepared.speech_ms, snr_db=prepared.snr_db)

        prompt = self._prompt(prompt)
        # Echo guard sees the static base prompt only (see base_prompt_for_echo).
        echo_ref = base_prompt_for_echo()
        result = self._attempt(prepared, self.model, prompt, echo_prompt=echo_ref)

        # Verify suspicious turbo output with the slower/more accurate model.
        if (
            result.status == "ok"
            and result.reason == "low_confidence"
            and settings.stt_verify_with_fallback
            and settings.stt_fallback_model
            and settings.stt_fallback_model != self.model
        ):
            try:
                alt = self._attempt(prepared, settings.stt_fallback_model, prompt, echo_prompt=echo_ref)
                if alt.status == "ok":
                    alt.reason = "verified"
                    return alt
            except Exception as e:  # noqa: BLE001
                print(f"[stt] verification failed: {e}")

        if result.status == "hallucination":
            # The fast model may hallucinate where the accurate model does not.
            if settings.stt_fallback_model and settings.stt_fallback_model != self.model:
                try:
                    alt = self._attempt(prepared, settings.stt_fallback_model, prompt, echo_prompt=echo_ref)
                    if alt.status == "ok":
                        alt.reason = "fallback_model"
                        return alt
                except Exception as e:  # noqa: BLE001
                    print(f"[stt] fallback model failed: {e}")
        return result

    def transcribe_bytes(self, audio_bytes: bytes, suffix: str = ".webm", prompt: str | None = None) -> str:
        result = self.transcribe_detailed(audio_bytes, suffix, prompt)
        return result.text


class FasterWhisperSTT:
    def __init__(self, model: str | None = None):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(model or "base", device="cpu", compute_type="int8")

    def transcribe_detailed(self, audio_bytes: bytes, suffix: str = ".webm", prompt: str | None = None) -> STTResult:
        prepared = prepare_audio(audio_bytes, suffix)
        if not prepared.ok:
            return STTResult(status="no_speech", reason=prepared.reason)
        started = time.time()
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(prepared.wav or b"")
            segments, _ = self.model.transcribe(
                path,
                language=settings.stt_language,
                condition_on_previous_text=False,
                no_speech_threshold=settings.stt_no_speech_threshold,
                log_prob_threshold=settings.stt_logprob_threshold,
                compression_ratio_threshold=settings.stt_compression_ratio_threshold,
                temperature=0.0,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            texts = [s.text.strip() for s in segments if s.text.strip()]
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        text = " ".join(texts).strip()
        status = "ok" if text and not is_hallucination(text, base_prompt_for_echo()) else "hallucination"
        return STTResult(
            text=text if status == "ok" else "",
            raw=text,
            status=status,
            model="faster-whisper",
            latency_ms=int((time.time() - started) * 1000),
            duration_ms=prepared.duration_ms,
            speech_ms=prepared.speech_ms,
            snr_db=prepared.snr_db,
        )

    def transcribe_bytes(self, audio_bytes: bytes, suffix: str = ".webm", prompt: str | None = None) -> str:
        return self.transcribe_detailed(audio_bytes, suffix, prompt).text


class ChainSTT:
    """Tries providers in order; remembers the one that worked."""

    def __init__(self, factories: list[tuple[str, Callable[[], STTService]]]):
        self.factories = factories
        self.active: STTService | None = None
        self.active_name: str = ""

    def transcribe_detailed(self, audio_bytes: bytes, suffix: str = ".webm", prompt: str | None = None) -> STTResult:
        if self.active is not None:
            try:
                return self.active.transcribe_detailed(audio_bytes, suffix, prompt)
            except Exception as e:  # noqa: BLE001
                print(f"[stt] {self.active_name} failed, falling back: {e}")
                self.active = None
                self.active_name = ""

        errors = []
        for name, factory in self.factories:
            try:
                svc = factory()
                result = svc.transcribe_detailed(audio_bytes, suffix, prompt)
                self.active = svc
                self.active_name = name
                return result
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}: {e}")
        raise RuntimeError("all STT providers failed -> " + " | ".join(errors))

    def transcribe_bytes(self, audio_bytes: bytes, suffix: str = ".webm", prompt: str | None = None) -> str:
        return self.transcribe_detailed(audio_bytes, suffix, prompt).text


_stt_instance: STTService | None = None


def get_stt() -> STTService:
    global _stt_instance
    if _stt_instance is None:
        if settings.stt_provider == "faster-whisper":
            _stt_instance = FasterWhisperSTT()
        elif settings.stt_provider == "groq":
            _stt_instance = ChainSTT(
                [
                    ("groq-primary", lambda: GroqSTT(settings.stt_model)),
                    ("groq-fallback", lambda: GroqSTT(settings.stt_fallback_model)),
                    ("faster-whisper", lambda: FasterWhisperSTT()),
                ]
            )
        else:
            raise ValueError(f"unknown stt provider: {settings.stt_provider}")
    return _stt_instance
