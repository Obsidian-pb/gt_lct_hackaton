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

    # --- ИИ-провайдер: ключ хранится только на сервере и не отдаётся браузеру ---
    ai_provider: str = ""  # openai | gigachat | gemini | anthropic | openai_compatible
    ai_api_key: str = ""  # Authorization-ключ провайдера (без "Basic "/"Bearer ")
    ai_model: str = "auto"  # auto — автоподбор из списка моделей, иначе точное имя
    ai_base_url: str = ""  # обязателен для openai_compatible
    ai_scope: str = "auto"  # scope GigaChat (GIGACHAT_API_PERS/B2B/CORP)
    ai_oauth_url: str = ""  # переопределение адреса OAuth GigaChat
    ai_ca_bundle: str = ""  # путь к CA-бандлу (иначе встроенный корневой сертификат)
    ai_verify_ssl: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()