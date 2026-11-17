from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "Project Management Service"
    ENV: str = "development"
    DEBUG: bool = True

    # Database
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "project_management"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # JWT / Auth
    JWT_SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60  # tokens last exactly 1 hour per spec

    # AWS / S3
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    AWS_SESSION_TOKEN: str | None = None  # required by AWS sandbox/temporary credentials
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = "project-management-documents"
    S3_ENDPOINT_URL: str | None = None  # useful for LocalStack / MinIO in dev

    # Business rules
    MAX_PROJECT_STORAGE_BYTES: int = 100 * 1024 * 1024  # 100 MB per project, enforced by Lambda

    # Sharing
    SHARE_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h join-link validity
    FRONTEND_BASE_URL: str = "http://localhost:8000"

    # Email (optional /share endpoint)
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "noreply@example.com"

    # AI assistant -- language model
    # "ollama" (free, runs locally), "anthropic", "openai", or "none" (no LLM:
    # the assistant returns the most relevant passages instead of a written answer)
    LLM_PROVIDER: str = "ollama"
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 1024
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "llama3.2"
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-haiku-4-5"
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # AI assistant -- embeddings
    # "ollama" (free, local), "huggingface" (local sentence-transformers; install
    # with `uv sync --extra huggingface`), or "hash" (no model at all; keyword-based,
    # used by the tests and for a zero-install demo)
    EMBEDDING_PROVIDER: str = "ollama"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
    HUGGINGFACE_EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    HASH_EMBEDDING_DIMENSIONS: int = 512

    # AI assistant -- retrieval and context management
    CHUNK_SIZE: int = 1000  # characters per chunk
    CHUNK_OVERLAP: int = 150  # characters shared between neighbouring chunks
    RAG_TOP_K: int = 4  # chunks passed to the model per question
    RAG_MIN_SCORE: float = 0.0  # only keep chunks MORE similar than this (cosine, -1..1)
    CHAT_HISTORY_TURNS: int = 6  # previous messages kept as conversation memory
    CONTEXT_CHAR_BUDGET: int = 12000  # max characters of document context per prompt
    AGENT_MAX_STEPS: int = 8  # safety limit for the LangGraph agent loop


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
