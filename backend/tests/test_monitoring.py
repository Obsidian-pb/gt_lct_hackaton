"""Состояние комплекса: запись сбоев, отчёт об ошибках, нагрузка на сервер.

Проверяется главное свойство раздела: он ничего не ломает. Сбой обязан быть
записан, но попытка его записать не вправе ни изменить ответ пользователю,
ни добавить второй отказ поверх первого.
"""

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import get_session
from app.main import app
from app.models.audit import ErrorEvent
from app.services import health
from tests.test_api import token


@pytest.fixture
def broken_client(db_factory, monkeypatch):
    """Клиент, у которого `/api/admin/system` гарантированно отказывает.

    Ломается настоящий обработчик, а не добавленный ради теста маршрут:
    проверять надо тот путь, которым сбой пойдёт в жизни, — через
    обработчик исключений всего приложения.

    raise_server_exceptions=False обязателен: иначе тестовый клиент
    перехватил бы исключение раньше и вернул бы его в тест вместо ответа,
    который получает браузер.
    """

    def boom() -> None:
        raise RuntimeError("Справочник ЕКП не читается")

    def override_session():
        with db_factory() as session:
            yield session

    monkeypatch.setattr("app.api.admin.get_ekp", boom)
    monkeypatch.setattr("app.main.SessionLocal", db_factory)
    app.dependency_overrides[get_session] = override_session
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def test_сбой_записывается_и_попадает_в_отчёт(broken_client):
    headers = token(broken_client, "root")

    failed = broken_client.get("/api/admin/system", headers=headers)
    assert failed.status_code == 500
    assert "Сбой записан" in failed.json()["detail"]

    report = broken_client.get("/api/admin/errors", headers=headers).json()
    assert report["total"] == 1
    record = report["recent"][0]
    assert record["kind"] == "RuntimeError"
    assert record["message"] == "Справочник ЕКП не читается"
    assert record["path"] == "/api/admin/system"
    assert record["method"] == "GET"
    # Логин берётся из предъявленного токена: по нему видно, у кого сломалось.
    assert record["actor_login"] == "root"
    assert "RuntimeError" in record["traceback"]


def test_отчёт_ограничен_запрошенным_периодом(broken_client, db_factory):
    headers = token(broken_client, "root")
    broken_client.get("/api/admin/system", headers=headers)
    with db_factory() as db:
        db.add(
            ErrorEvent(
                at=datetime.now(timezone.utc) - timedelta(days=3),
                path="/api/attempts/my",
                method="GET",
                kind="OSError",
                message="соединение с базой потеряно",
            )
        )
        db.commit()

    за_сутки = broken_client.get("/api/admin/errors?hours=24", headers=headers).json()
    за_неделю = broken_client.get("/api/admin/errors?hours=168", headers=headers).json()
    assert за_сутки["total"] == 1
    assert за_неделю["total"] == 2


def test_отчёт_группирует_одинаковые_сбои(broken_client):
    headers = token(broken_client, "root")
    for _ in range(3):
        broken_client.get("/api/admin/system", headers=headers)

    report = broken_client.get("/api/admin/errors", headers=headers).json()
    assert report["total"] == 3
    assert len(report["groups"]) == 1
    group = report["groups"][0]
    assert group["kind"] == "RuntimeError"
    assert group["count"] == 3
    assert group["last_at"] is not None


def test_неудачная_запись_сбоя_не_меняет_ответ(broken_client, monkeypatch):
    """Отказавшая база — это ровно тот случай, когда сбои и происходят."""

    def no_database():
        raise OSError("соединение с базой потеряно")

    monkeypatch.setattr("app.main.SessionLocal", no_database)
    headers = token(broken_client, "root")

    failed = broken_client.get("/api/admin/system", headers=headers)
    assert failed.status_code == 500
    assert "Сбой записан" in failed.json()["detail"]


def test_в_сбое_не_сохраняется_содержимое_запроса(broken_client, db_factory):
    """Тело и строка запроса не пишутся: в них попадает работа обучающегося."""
    headers = token(broken_client, "root")
    broken_client.get("/api/admin/system?секрет=текст-работы", headers=headers)

    with db_factory() as db:
        event = db.scalars(select(ErrorEvent)).one()
    assert event.path == "/api/admin/system"
    assert "секрет" not in (event.path or "")


def test_состояние_комплекса_видно_администратору(admin_client):
    headers = token(admin_client, "root")
    state = admin_client.get("/api/admin/health", headers=headers).json()

    assert state["database"]["ok"] is True
    assert state["database"]["response_ms"] is not None
    assert state["uptime_seconds"] >= 0
    # В тестах провайдер — заглушка: внешних обращений раздел не делает.
    assert state["llm"]["provider"] == "stub"
    assert state["llm"]["ok"] is True
    assert state["errors_24h"] == 0
    for показатель in ("cpu", "memory", "disk"):
        assert показатель in state["load"]


def test_недоступный_показатель_не_роняет_страницу_состояния(admin_client, monkeypatch):
    """На Windows нет ни cgroup, ни statvfs — страница обязана открыться всё равно.

    Заказчик открыл «Состояние» в переносном комплекте и получил «внутреннюю
    ошибку»: падал один показатель, а с ним и вся страница.
    """

    def no_such_call():
        raise AttributeError("module 'os' has no attribute 'statvfs'")

    monkeypatch.setattr(health, "_disk", no_such_call)
    headers = token(admin_client, "root")

    response = admin_client.get("/api/admin/health", headers=headers)
    assert response.status_code == 200, response.text
    disk = response.json()["load"]["disk"]
    assert disk["percent"] is None and disk["total_bytes"] is None
    assert "недоступны" in disk["note"]
    # Остальные показатели приходят как обычно.
    assert "scope" in response.json()["load"]["cpu"]


def test_отсутствие_резервных_копий_не_выдаётся_за_исправность(admin_client, tmp_path, monkeypatch):
    """Каталог копий контейнеру приложения может быть не виден — это не «ок»."""
    monkeypatch.setattr(health, "BACKUP_DIR", tmp_path / "нет-такого-каталога")
    headers = token(admin_client, "root")

    backups = admin_client.get("/api/admin/health", headers=headers).json()["backups"]
    assert backups["ok"] is None
    assert "не виден" in backups["note"]


def test_свежая_резервная_копия_считается_исправной(admin_client, tmp_path, monkeypatch):
    """Разбираются те же отметки, что оставляет ops/backup/backup.sh."""
    (tmp_path / "last-success").write_text(f"{int(time.time())} 20260920T003001Z\n")
    (tmp_path / "trainer-20260920T003001Z.dump").write_bytes(b"PGDMP")
    (tmp_path / "latest.dump").write_bytes(b"PGDMP")
    monkeypatch.setattr(health, "BACKUP_DIR", tmp_path)
    headers = token(admin_client, "root")

    backups = admin_client.get("/api/admin/health", headers=headers).json()["backups"]
    assert backups["ok"] is True
    assert backups["count"] == 1
    assert backups["age_hours"] < 1
    assert backups["last_failure"] is None


def test_устаревшая_резервная_копия_видна_как_отказ(admin_client, tmp_path, monkeypatch):
    старая = int(time.time()) - int(health.BACKUP_MAX_AGE_HOURS * 3600) - 60
    (tmp_path / "last-success").write_text(f"{старая} 20260901T003001Z\n")
    (tmp_path / "latest.dump").write_bytes(b"PGDMP")
    (tmp_path / "last-failure").write_text("2026-09-20T00:30:01Z pg_dump завершился с ошибкой\n")
    monkeypatch.setattr(health, "BACKUP_DIR", tmp_path)
    headers = token(admin_client, "root")

    backups = admin_client.get("/api/admin/health", headers=headers).json()["backups"]
    assert backups["ok"] is False
    assert "копирование остановилось" in backups["note"]
    assert "pg_dump" in backups["last_failure"]


def test_нагрузка_считается_по_пределам_контейнера(tmp_path, monkeypatch):
    """Разбор файлов cgroup v2 — так их видит приложение внутри контейнера.

    Проверяется на подставном каталоге: на рабочей машине разработчика
    (и в этих тестах) ни /sys/fs/cgroup, ни /proc нет, а ошибиться в разборе
    легко — и увидели бы мы это только на сервере.
    """
    (tmp_path / "cpu.stat").write_text("usage_usec 2000000\nuser_usec 1500000\n")
    (tmp_path / "cpu.max").write_text("150000 100000\n")
    (tmp_path / "memory.current").write_text("400000000\n")
    (tmp_path / "memory.max").write_text("805306368\n")
    (tmp_path / "memory.stat").write_text("anon 250000000\ninactive_file 100000000\n")
    monkeypatch.setattr(health, "CGROUP", tmp_path)
    monkeypatch.setattr(health, "_cpu_previous", None)

    первый = health.load()
    # Первый замер только запоминает точку отсчёта: доли процессора ещё нет.
    assert первый["cpu"]["percent"] is None
    assert первый["cpu"]["limit_cores"] == 1.5
    # Память показывается без файлового кеша и от предела контейнера,
    # а не от памяти всего сервера.
    assert первый["memory"]["used_bytes"] == 300_000_000
    assert первый["memory"]["limit_bytes"] == 805_306_368
    assert первый["memory"]["percent"] == 37.3

    # Секундой позже израсходовано ещё полтора процессорных ядра-секунды —
    # это ровно тот предел, который отведён контейнеру.
    import time as _time

    monkeypatch.setattr(health, "_cpu_previous", (_time.monotonic() - 1.0, 0.5))
    assert health.load()["cpu"]["percent"] == 100.0


def test_контейнер_без_предела_памяти_говорит_об_этом_прямо(tmp_path, monkeypatch):
    (tmp_path / "memory.current").write_text("400000000\n")
    (tmp_path / "memory.max").write_text("max\n")
    (tmp_path / "memory.stat").write_text("inactive_file 0\n")
    monkeypatch.setattr(health, "CGROUP", tmp_path)

    memory = health.load()["memory"]
    assert "предел не задан" in memory["scope"]


@pytest.mark.parametrize("логин", ["student", "teacher"])
def test_состояние_комплекса_закрыто_обучающемуся_и_преподавателю(admin_client, логин):
    headers = token(admin_client, логин)
    assert admin_client.get("/api/admin/health", headers=headers).status_code == 403
    assert admin_client.get("/api/admin/errors", headers=headers).status_code == 403
