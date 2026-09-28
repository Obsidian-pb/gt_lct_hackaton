"""Настройки ИИ-микросервиса.

Ключ провайдера и токен доступа живут только здесь (env / config.local.json)
и не передаются ни браузеру, ни backend_new: интеграция идёт по HTTPS
с Bearer-токеном микросервиса.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "System-112 AI Service"
    app_version: str = "0.1.0"
    debug: bool = False

    # Токен доступа: backend_new отправляет его в Authorization: Bearer <AI_SERVICE_TOKEN>.
    # Значение по умолчанию — заглушка: без явной настройки сервис отвечает 503.
    ai_service_token: str = "change-me-ai-service-token"

    # Разрешённые источники (backend_new и локальный фронт разработки).
    cors_origins: list[str] = [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
    ]

    # --- ИИ-провайдер: ключ хранится только на этом сервере -----------------
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