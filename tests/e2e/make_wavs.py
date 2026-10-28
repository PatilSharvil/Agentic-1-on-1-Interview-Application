"""Generate WAV speech files for the E2E interview using Windows SAPI TTS.

Candidate answers are scripted to feed the knowledge graph:
  - skills mentioned in answers (Redis, Kubernetes, PostgreSQL, ...)
  - claims with evidence ("cut p95 latency from 900ms to 120ms")
  - one deliberate contradiction for the final adaptive follow-up
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
WAVS = HERE / "wavs"

ANSWERS = {
    "a1": (
        "At Finlytics I built the payments API with FastAPI and PostgreSQL. "
        "It processes about two million requests per day. I used SQLAlchemy async "
        "sessions and Pydantic schemas, and the pytest suite covers 85 percent of the code."
    ),
    "a2": (
        "We scaled the service with Redis caching and Celery workers running on Kubernetes. "
        "I wrote the Helm charts myself and tuned the autoscaling based on p 95 latency. "
        "That cut the p 95 from 900 milliseconds down to 120 milliseconds."
    ),
    "a3": (
        "During one outage I traced the problem to connection pool exhaustion in PostgreSQL. "
        "I added pgBouncer in front of the database and set up Grafana dashboards "
        "with alerting so we would catch it earlier next time."
    ),
    "a4": (
        "I own the GitHub Actions pipeline. Docker images are built with multi stage builds, "
        "scanned with Trivy, and deployed with Terraform to AWS EKS. "
        "Every merge to main goes out automatically."
    ),
    "a5": (
        "Early at DataHive I split a monolith into microservices too early, "
        "and it made the Kafka ingestion harder to debug. "
        "I learned to measure first, and now I prototype behind feature flags before committing."
    ),
    # Deliberate contradiction: the resume claims Kubernetes production experience,
    # this answer walks it back -> the graph should record a contradicts edge.
    "adaptive_final": (
        "To be honest, I have never actually run Kubernetes in production myself. "
        "At Finlytics we used Docker Compose on a single AWS instance, "
        "and another team managed the EKS cluster."
    ),
}

QUESTION_PREFIX = "interviewer_q"


def tts(text: str, path: Path, rate: int = 0) -> None:
    safe = text.replace('"', "'" ).replace("\n", " ")
    ps = (
        'Add-Type -AssemblyName System.Speech; '
        '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
        + (f'$s.Rate = {rate}; ' if rate else '')
        + f'$s.SetOutputToWaveFile("{path}"); '
        + f'$s.Speak("{safe}"); '
        + '$s.Dispose()'
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        check=True, capture_output=True, timeout=120,
    )


def make_answers() -> dict[str, Path]:
    WAVS.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, text in ANSWERS.items():
        p = WAVS / f"{key}.wav"
        if not p.exists():
            tts(text, p)
        out[key] = p
    return out


def make_question(text: str, idx: int) -> Path:
    WAVS.mkdir(parents=True, exist_ok=True)
    p = WAVS / f"{QUESTION_PREFIX}_{idx}.wav"
    if not p.exists():
        tts(f"Question {idx}. {text}", p)
    return p


if __name__ == "__main__":
    paths = make_answers()
    for k, v in paths.items():
        print(k, v, v.stat().st_size, "bytes")
