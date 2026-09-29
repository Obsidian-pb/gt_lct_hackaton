from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "System-112 Trainer API"
    app_version: str = "0.1.0"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str = (
        "postgresql+asyncpg://system112:system112@localhost:5432/system112_trainer"
    )

    jwt_secret_key: str = "dev-only-secret-key-change-me-in-production-0123456789"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7

    cors_origins: list[str] = ["*"]

    # --- ИИ-микросервис: ключ провайдера хранится ТОЛЬКО в ai_service.
    # backend_new обращается к нему по HTTP с Bearer AI_SERVICE_TOKEN. ---
    ai_service_url: str = "http://127.0.0.1:8890"
    ai_service_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()