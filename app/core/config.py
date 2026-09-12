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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
