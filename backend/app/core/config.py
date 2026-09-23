from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://trainer:trainer@localhost:5432/trainer"
    secret_key: str = "dev-secret-change-me"

    # Пул соединений с базой. Значения по умолчанию рассчитаны на норматив
    # ТЗ — сто одновременных пользователей — и проверены scripts/loadtest.py.
    db_pool_size: int = 20
    db_pool_overflow: int = 30
    db_pool_timeout_seconds: float = 10.0
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
    # Отключает «размышление» у рассуждающих моделей (Qwen3 и подобные).
    # На проверке комментария это сокращает ответ с 31 до 2,5 секунд и
    # повышает точность. Поле понимают llama.cpp и vLLM, но не внешний
    # OpenAI API — поэтому передаётся только при явном включении.
    llm_disable_thinking: bool = False

    # --- GigaChat ----------------------------------------------------------
    # Ключ авторизации из личного кабинета (base64) либо пара
    # client_id:client_secret — провайдер принимает оба вида.
    gigachat_auth_key: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat"
    # Путь к корневому сертификату НУЦ Минцифры. Пустое значение оставляет
    # системное хранилище; False отключает проверку — только для отладки.
    gigachat_ca_bundle: str = ""
    gigachat_verify_tls: bool = True

    # --- Журналирование ----------------------------------------------------
    # Глубина хранения журнала аудита. Шесть месяцев — нижняя граница из ТЗ,
    # ниже её значение не принимается ни из окружения, ни из интерфейса.
    audit_retention_days: int = 180
    # Подробность журнала приложения: ERROR, WARNING, INFO или DEBUG.
    log_level: str = "INFO"

    ekp_path: Path = BASE_DIR / "data" / "ekp.json"

    # Каталог собранного фронтенда, который раздаёт само приложение.
    # В контейнерной поставке пусто — фронт раздаёт nginx. Значение задаёт
    # переносной комплект для Windows, где nginx нет и один процесс
    # обслуживает и API, и страницы.
    static_dir: Path | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
