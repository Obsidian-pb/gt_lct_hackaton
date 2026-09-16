from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://trainer:trainer@localhost:5432/trainer"
    secret_key: str = "dev-secret-change-me"
    access_token_ttl_minutes: int = 12 * 60

    # Норматив подтверждения приёма карточки диспетчером ДДС.
    # 30 секунд — требование ПП РФ № 1931, не произвольная настройка.
    default_response_deadline_seconds: int = 30

    # Провайдер ИИ-оценки: "openai" — внешний API, "local" — локальный
    # OpenAI-совместимый эндпоинт (Ollama/vLLM), "stub" — без LLM.
    llm_provider: str = "stub"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 60.0

    ekp_path: Path = BASE_DIR / "data" / "ekp.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
