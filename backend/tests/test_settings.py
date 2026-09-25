"""Раздел «Конфигурация»: настройка модели и параметры журналирования.

Проверяется главным образом то, что ломается молча: утечка ключа доступа
в ответ, случайное стирание ключа при правке соседнего поля, настройка,
которая сохранилась, но не подействовала, и срок хранения журнала ниже
требования ТЗ.
"""

import httpx
import pytest

from app.core.config import get_settings
from app.llm import explain_llm_failure, get_llm_provider, reset_llm_provider
from app.models.audit import AuditAction
from app.services import system_settings
from tests.test_api import token

SECRET = "sk-test-secret-1234"


@pytest.fixture
def env_llm(monkeypatch):
    """Переменные окружения такие, как при первом запуске комплекса."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_MODEL", "модель-из-окружения")
    monkeypatch.setenv("LLM_API_KEY", "ключ-из-окружения")
    get_settings.cache_clear()
    yield
    # Кеш чистится и на выходе: иначе следующий тест получил бы настройки
    # этого, уже без переменных окружения.
    get_settings.cache_clear()


@pytest.fixture
def llm_from_db(monkeypatch, db_factory):
    """Провайдер собирается по временной базе теста, а не по рабочей."""
    monkeypatch.setattr("app.services.system_settings.SessionLocal", db_factory)
    reset_llm_provider()
    yield
    # Кеш провайдера живёт в модуле и пережил бы тест вместе с HTTP-клиентом.
    reset_llm_provider()


def save_llm(client, headers, **overrides) -> dict:
    body = {
        "provider": "local",
        "base_url": "http://127.0.0.1:8095/v1",
        "model": "qwen3",
        "api_key": "",
        "disable_thinking": False,
    }
    body.update(overrides)
    response = client.put("/api/admin/settings/llm", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_ключ_модели_не_отдаётся_наружу(admin_client):
    headers = token(admin_client, "root")
    saved = save_llm(admin_client, headers, api_key=SECRET)

    # Ни в ответе на сохранение, ни при последующем чтении — только признак.
    assert saved["api_key_set"] is True
    assert SECRET not in admin_client.put(
        "/api/admin/settings/llm",
        json={
            "provider": "local",
            "base_url": "http://127.0.0.1:8095/v1",
            "model": "qwen3",
            "api_key": SECRET,
            "disable_thinking": False,
        },
        headers=headers,
    ).text
    read = admin_client.get("/api/admin/settings", headers=headers)
    assert SECRET not in read.text
    assert read.json()["llm"]["api_key_set"] is True


def test_ключ_модели_не_попадает_в_журнал_аудита(admin_client):
    """Запись аудита живёт полгода и читается с экрана — ключу там не место."""
    headers = token(admin_client, "root")
    save_llm(admin_client, headers, api_key=SECRET)

    events = admin_client.get("/api/admin/audit", headers=headers)
    assert SECRET not in events.text
    latest = events.json()[0]
    assert latest["action"] == str(AuditAction.SETTINGS_LLM_UPDATED)
    assert latest["detail"]["ключ"] == "изменён"
    assert latest["detail"]["внешний контур"] == "нет"


def test_пустой_ключ_не_стирает_сохранённый(admin_client, db_factory):
    """Правка адреса не должна стирать ключ, которого в форме и не видно."""
    headers = token(admin_client, "root")
    save_llm(admin_client, headers, api_key=SECRET)

    updated = save_llm(admin_client, headers, base_url="http://127.0.0.1:9000/v1")
    assert updated["api_key_set"] is True
    assert updated["base_url"] == "http://127.0.0.1:9000/v1"

    with db_factory() as db:
        assert system_settings.llm_config(db).api_key == SECRET


def test_ключ_стирается_только_явным_действием(admin_client, db_factory, env_llm):
    headers = token(admin_client, "root")
    save_llm(admin_client, headers, api_key=SECRET)

    cleared = admin_client.post("/api/admin/settings/llm/key/clear", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["api_key_set"] is False

    with db_factory() as db:
        # Пустое значение записано в базу, а не удалено: иначе вернулся бы
        # ключ из переменной окружения, который и отключали.
        assert system_settings.llm_config(db).api_key == ""

    events = admin_client.get("/api/admin/audit", headers=headers).json()
    assert events[0]["action"] == str(AuditAction.SETTINGS_LLM_KEY_CLEARED)


def test_настройка_из_базы_перекрывает_переменную_окружения(admin_client, db_factory, env_llm):
    headers = token(admin_client, "root")

    # До правки действует начальное состояние из окружения.
    before = admin_client.get("/api/admin/settings", headers=headers).json()["llm"]
    assert before["provider"] == "openai"
    assert before["model"] == "модель-из-окружения"
    assert before["api_key_set"] is True

    saved = save_llm(admin_client, headers, model="qwen3-coder")
    # Отметка «кто и когда» приходит уже в ответе на сохранение, а не только
    # при следующем чтении: иначе раздел показывал бы «не менялось».
    assert saved["updated_at"] and saved["updated_by"] == "root"

    after = admin_client.get("/api/admin/settings", headers=headers).json()["llm"]
    assert after["provider"] == "local"
    assert after["model"] == "qwen3-coder"
    assert after["updated_by"] == "root"
    with db_factory() as db:
        assert system_settings.llm_config(db).model == "qwen3-coder"


def test_смена_провайдера_действует_без_перезапуска(admin_client, llm_from_db):
    """Иначе настройку пришлось бы применять перезапуском контейнера."""
    headers = token(admin_client, "root")
    assert get_llm_provider().name == "stub"

    save_llm(admin_client, headers, model="qwen3", base_url="http://127.0.0.1:8095/v1")

    provider = get_llm_provider()
    assert provider.name == "local"
    assert str(provider._client.base_url).rstrip("/") == "http://127.0.0.1:8095/v1"

    save_llm(admin_client, headers, provider="stub")
    assert get_llm_provider().name == "stub"


def test_внешний_контур_виден_в_настройке(admin_client):
    """Предупреждению в интерфейсе нужен признак, а не догадка по названию."""
    headers = token(admin_client, "root")
    assert save_llm(admin_client, headers)["external"] is False
    assert save_llm(admin_client, headers, base_url="https://api.openai.com/v1")["external"]


def test_неполная_настройка_модели_не_сохраняется(admin_client):
    headers = token(admin_client, "root")
    without_model = admin_client.put(
        "/api/admin/settings/llm",
        json={"provider": "local", "base_url": "http://127.0.0.1:8095/v1", "model": ""},
        headers=headers,
    )
    assert without_model.status_code == 422
    assert "имя модели" in without_model.json()["detail"]

    bad_url = admin_client.put(
        "/api/admin/settings/llm",
        json={"provider": "local", "base_url": "127.0.0.1:8095", "model": "qwen3"},
        headers=headers,
    )
    assert bad_url.status_code == 422
    assert "http://" in bad_url.json()["detail"]


def test_глубина_хранения_меньше_полугода_отвергается(admin_client):
    headers = token(admin_client, "root")
    response = admin_client.put(
        "/api/admin/settings/logging",
        json={"audit_retention_days": 30, "level": "INFO"},
        headers=headers,
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    # Отказ должен объяснять причину, а не просто не принимать значение.
    assert "180" in detail and "шести месяцев" in detail


def test_параметры_журналирования_сохраняются(admin_client):
    import logging

    headers = token(admin_client, "root")
    response = admin_client.put(
        "/api/admin/settings/logging",
        json={"audit_retention_days": 365, "level": "DEBUG"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["audit_retention_days"] == 365
    assert body["level"] == "DEBUG"
    assert body["min_audit_retention_days"] == 180
    # Подробность применяется сразу: перезапуска у администратора нет.
    assert logging.getLogger().level == logging.DEBUG
    logging.getLogger().setLevel(logging.WARNING)

    events = admin_client.get("/api/admin/audit", headers=headers).json()
    assert events[0]["action"] == str(AuditAction.SETTINGS_LOGGING_UPDATED)
    assert events[0]["detail"]["подробность"] == "DEBUG"


def test_проверка_связи_работает_на_несохранённой_настройке(admin_client):
    """Проверить настройку надо до того, как она подействует на занятие."""
    headers = token(admin_client, "root")
    # Порт 1 заведомо никем не занят: проверяется именно разбор отказа.
    response = admin_client.post(
        "/api/admin/llm/test",
        json={"provider": "local", "base_url": "http://127.0.0.1:1/v1", "model": "qwen3"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "подключиться" in body["detail"]

    # Сохранённая настройка при этом не изменилась.
    assert admin_client.get("/api/admin/settings", headers=headers).json()["llm"][
        "provider"
    ] == "stub"


def test_проверка_связи_без_модели_не_ошибка(admin_client):
    headers = token(admin_client, "root")
    body = admin_client.post("/api/admin/llm/test", json={}, headers=headers).json()
    assert body["ok"] is True
    assert body["provider"] == "stub"


@pytest.mark.parametrize(
    "exc,expected",
    [
        (
            httpx.HTTPStatusError(
                "401",
                request=httpx.Request("POST", "http://x/v1/chat/completions"),
                response=httpx.Response(401, text="no key"),
            ),
            "ключ доступа",
        ),
        (
            httpx.HTTPStatusError(
                "404",
                request=httpx.Request("POST", "http://x/v1/chat/completions"),
                response=httpx.Response(404, text="model not found"),
            ),
            "/v1",
        ),
        (httpx.ConnectTimeout("timeout"), "не ответила"),
    ],
)
def test_отказ_модели_объясняется_по_русски(exc, expected):
    """Администратору недоступны журналы контейнеров: причина нужна на экране."""
    assert expected in explain_llm_failure(exc)


def test_конфигурация_закрыта_преподавателю_и_обучающемуся(client):
    for login in ("teacher", "student"):
        headers = token(client, login)
        assert client.get("/api/admin/settings", headers=headers).status_code == 403
        assert (
            client.put(
                "/api/admin/settings/llm",
                json={"provider": "stub", "base_url": "", "model": ""},
                headers=headers,
            ).status_code
            == 403
        )
        assert (
            client.put(
                "/api/admin/settings/logging",
                json={"audit_retention_days": 200, "level": "INFO"},
                headers=headers,
            ).status_code
            == 403
        )
        assert (
            client.post("/api/admin/settings/llm/key/clear", headers=headers).status_code == 403
        )
        assert client.post("/api/admin/llm/test", json={}, headers=headers).status_code == 403


def test_ключ_с_кириллицей_отклоняется_с_объяснением(admin_client):
    """Такой ключ уходил в HTTP-заголовок и ронял каждый запрос к модели ошибкой кодировки."""
    headers = token(admin_client, "root")
    body = {"provider": "local", "base_url": "http://127.0.0.1:8095/v1", "model": "qwen3",
            "api_key": "вставьте ключ", "disable_thinking": False}
    response = admin_client.put("/api/admin/settings/llm", json=body, headers=headers)
    assert response.status_code == 422
    assert "недопустимые символы" in response.json()["detail"]
