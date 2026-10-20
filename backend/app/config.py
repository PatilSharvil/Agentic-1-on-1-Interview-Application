from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "meeting-platform"
    database_url: str = "sqlite+aiosqlite:///./meeting.db"
    secret_key: str = "change-me-in-prod"
    access_token_expire_minutes: int = 60 * 24
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5133", "http://127.0.0.1:5133"]
    stt_provider: str = "groq"  # groq | faster-whisper | deepgram | openai
    stt_model: str = "whisper-large-v3-turbo"
    stt_fallback_model: str = "whisper-large-v3"
    stt_prompt: str = "Interview about software engineering. Technical terms: Python, JavaScript, TypeScript, React, FastAPI, Docker, Kubernetes, SQL, Git, REST API, microservices, CI/CD, AWS, cloud computing, Node.js, PostgreSQL, Redis, GraphQL."
    groq_api_key: str = ""
    llm_model: str = "qwen/qwen3.8-27b"
    openrouter_api_key: str = ""
    openrouter_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    openrouter_fallback: str = "openrouter/free"


settings = Settings()