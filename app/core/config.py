"""
app/core/config.py

Application settings (Pydantic BaseSettings updated for pydantic v2 + pydantic-settings).

Notes:
- BaseSettings has moved to the pydantic-settings package for pydantic v2.
  Install it with: pip install pydantic-settings
- We use SettingsConfigDict to configure env_file and encoding.
- Keep attribute names uppercase so they map to environment variables directly.
"""
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Configure pydantic-settings: read .env by default
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # App / env
    APP_ENV: str = Field("development")

    # Database
    DATABASE_URL: str = Field("sqlite:///./data/app.db")

    # Reports
    REPORTS_DIR: str = Field("./data/reports")
    ADMIN_EMAIL: str = Field("anand@gmail.com")

    # Email / SMTP
    MAIL_TRANSPORT: str = Field("mailhog")
    SMTP_HOST: str = Field("localhost")
    SMTP_PORT: int = Field(1025)
    SMTP_USER: str = Field("")
    SMTP_PASSWORD: str = Field("")
    SMTP_USE_TLS: bool = Field(False)

    # Celery / Redis
    RESULT_BACKEND: str = Field("redis://127.0.0.1:6379/0")
    BROKER_URL: str = Field("redis://127.0.0.1:6379/0")
    CAMPAIGN_SCHEDULER_INTERVAL_SECONDS : int = Field(50)


    # Tuning
    BATCH_SIZE: int = Field(200)
    SEND_RETRY_COUNT: int = Field(3)
    SEND_RETRY_BACKOFF: int = Field(2)
    WORKER_CONCURRENCY: int = Field(4)
    RATE_LIMIT: str = Field("10/s")

    # Observability
    PROMETHEUS_ENABLED: bool = Field(False)

@lru_cache()
def get_settings() -> Settings:
    """
    Return a cached Settings instance. Use this in modules to avoid re-reading env on every import.
    """
    return Settings()