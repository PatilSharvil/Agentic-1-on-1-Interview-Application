from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    app_name: str = "meeting-platform"
    database_url: str = "sqlite+aiosqlite:///./meeting.db"
    secret_key: str = "change-me-in-prod"
    access_token_expire_minutes: int = 60 * 24
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5133", "http://127.0.0.1:5133"]

    # ---- STT ----
    stt_provider: str = "groq"  # groq | faster-whisper
    # large-v3 is the most accurate Groq Whisper model; turbo is the fast fallback.
    stt_model: str = "whisper-large-v3"
    stt_fallback_model: str = "whisper-large-v3-turbo"
    stt_language: str = "en"
    # Keep this SHORT. Groq Whisper echoes long prompts back as "hallucinations".
    # The candidate name and resume skills are appended per room at runtime.
    stt_prompt: str = (
        "Technical interview about Python, FastAPI, PostgreSQL, Redis, Kubernetes, Docker, AWS and Terraform."
    )
    stt_use_prompt: bool = True
    stt_prompt_max_words: int = 40
    # safe = deterministic cleanup only, llm = guarded LLM polish, off = none
    stt_cleanup: str = "llm"
    stt_min_speech_ms: int = 320
    stt_logprob_threshold: float = -1.10
    stt_no_speech_threshold: float = 0.55
    stt_compression_ratio_threshold: float = 2.4
    # large-v3 is primary; do not "verify" it with the weaker turbo model.
    stt_verify_with_fallback: bool = False
    # Open-source denoising is available but OFF by default: RNNoise and
    # DeepFilterNet both degraded some transcripts in our WER tests. The browser
    # already applies WebRTC noise suppression, and VAD rejects non-speech.
    stt_denoise: str = "off"  # off | deepfilter | rnnoise
    stt_denoise_below_snr_db: float = 15.0
    stt_highpass_hz: int = 80
    stt_glossary: str = (
        "Python,JavaScript,TypeScript,React,FastAPI,Node.js,Docker,Kubernetes,PostgreSQL,MySQL,"
        "SQL,NoSQL,Redis,GraphQL,REST,API,CI/CD,AWS,GCP,Azure,Git,GitHub,Java,C++,C#,Go,Rust,"
        "Django,Flask,Spring Boot,MongoDB,Terraform,Linux,Nginx,WebSocket,Microservices"
    )
    groq_api_key: str = ""

    # ---- LLM (fast primary on Groq, OpenRouter as fallback) ----
    llm_provider: str = "groq"
    llm_model: str = "openai/gpt-oss-20b"
    llm_secondary_model: str = "openai/gpt-oss-120b"
    llm_graph_model: str = "openai/gpt-oss-20b"
    llm_reasoning_effort: str = "low"
    llm_timeout_s: float = 45.0
    openrouter_api_key: str = ""
    openrouter_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    openrouter_fallback: str = "openrouter/free"

    # ---- Knowledge graph ----
    graph_auto_rebuild: bool = True
    graph_rebuild_debounce_s: float = 5.0
    graph_max_nodes: int = 90
    graph_max_edges: int = 120
    graph_llm_enrich: bool = True


settings = Settings()
