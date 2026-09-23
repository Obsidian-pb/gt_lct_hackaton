"""Редакции классификатора: загрузка, включение и привязка занятий.

Главное свойство, которое сторожат эти проверки: занятие оценивается по той
редакции, по которой шло, сколько бы редакций администратор ни включил
после. Иначе отчёт разошёлся бы с тем, что обучающийся видел на экране.
"""

import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import select

from app.core.config import BASE_DIR, get_settings
from app.models.audit import AuditAction, AuditEvent
from app.models.training import (
    Attempt,
    CallOutcome,
    ClassifierVersion,
    Scenario,
    SessionState,
    TrainingMode,
    TrainingSession,
)
from app.models.user import DispatchService, User
from app.services import classifier_versions as service
from app.services.ekp import get_ekp
from app.services.ekp_import import ParseError, parse_workbook
from tests.test_api import token

FIRES = "Пожары и задымления"
FIRE_TRASH = 1010101
SMOKE_TRASH = 1010102

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def workbook(rules: list[tuple[int, tuple[str, ...], str, dict[str, str]]]) -> bytes:
    """Книга в формате исходного классификатора: три строки шапки, группа, правила.

    Службы: МЧС (одна колонка), МВД (две подколонки: по умолчанию и при
    пострадавших) и «Классификатор СМП», у которого приставка снимается.
    """
    book = openpyxl.Workbook()
    sheet = book.active
    header1 = [None] * 13 + ["МЧС", "МВД", None, "Классификатор СМП"]
    header2 = [None] * 17
    header3 = [None] * 13 + ["МЧС", "Признак не выбран", "Пострадавшие/погибшие", "СМП"]
    sheet.append(header1)
    sheet.append(header2)
    sheet.append(header3)
    sheet.append([None] * 4 + [1, FIRES])
    for number, signs, incident_type, notified in rules:
        row = [None] * 17
        row[4] = number
        row[5] = "мусор"
        row[6:9] = list(signs) + [None] * (3 - len(signs))
        row[10] = incident_type
        row[12] = "MCHS"
        row[13] = notified.get("МЧС")
        row[14] = notified.get("МВД")
        row[15] = notified.get("МВД+пострадавшие")
        row[16] = notified.get("СМП")
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# Две редакции одного и того же происшествия: во второй у горящего мусора
# другое название типа, а у задымления — другая подколонка МВД.
EDITION_2026 = workbook(
    [
        (FIRE_TRASH, ("на улице", "мусор", "открытое пламя"), "пожар: мусор",
         {"МЧС": "пожар: мусор", "МВД+пострадавшие": "пожар", "СМП": "нет реагирования"}),
        (SMOKE_TRASH, ("на улице", "мусор", "дым"), "задымление: мусор",
         {"МЧС": "задымление"}),
    ]
)
EDITION_2027 = workbook(
    [
        (FIRE_TRASH, ("на улице", "мусор", "открытое пламя"), "пожар: мусор (ред. 2027)",
         {"МЧС": "пожар: мусор", "МВД": "пожар", "СМП": "пострадавшие"}),
        (SMOKE_TRASH, ("на улице", "мусор", "дым"), "задымление: мусор",
         {"МЧС": "задымление", "МВД": "задымление"}),
    ]
)


def upload(client, headers, data: bytes, label: str, **fields):
    form = {"label": label, **fields}
    return client.post(
        "/api/admin/classifier/versions",
        files={"file": (f"{label}.xlsx", data, XLSX)},
        data=form,
        headers=headers,
    )


@pytest.fixture(autouse=True)
def _fresh_cache():
    # База пересоздаётся на каждый тест, а кеш разобранных редакций живёт
    # в процессе: ключ защищён контрольной суммой, но чистота нагляднее.
    service.reset_cache()
    yield
    service.reset_cache()


# --- Разбор xlsx как функция ---------------------------------------------------


def test_разбор_исходного_xlsx_тождественен_файлу_поставки():
    """Функция разбора и скрипт сборки обязаны давать один и тот же результат."""
    source = BASE_DIR.parent / "classificator.xlsx"
    shipped = Path(get_settings().ekp_path)
    if not source.exists() or not shipped.exists():
        pytest.skip("нет исходного classificator.xlsx или собранного ekp.json")

    result = parse_workbook(source.read_bytes(), source=source.name)
    expected = json.loads(shipped.read_text(encoding="utf-8"))
    assert result.rule_count == 1283
    assert result.unknown_variants == []
    assert result.payload == expected


def test_разбор_маленькой_книги_даёт_правила_и_подколонки():
    result = parse_workbook(EDITION_2026, source="test.xlsx")
    assert result.rule_count == 2
    assert result.payload["groups"] == [FIRES]
    assert result.payload["services"] == ["МВД", "МЧС", "СМП"]

    rule = next(r for r in result.payload["rules"] if r["number"] == FIRE_TRASH)
    assert rule["signs"] == ["на улице", "мусор", "открытое пламя"]
    flagged = next(n for n in rule["notifications"] if n["service"] == "МВД")
    assert flagged["requires_flags"] == ["пострадавшие"]


def test_негодный_файл_отклоняется_с_объяснением():
    with pytest.raises(ParseError, match="не читается"):
        parse_workbook("это не xlsx".encode())
    empty = openpyxl.Workbook()
    buffer = io.BytesIO()
    empty.save(buffer)
    with pytest.raises(ParseError):
        parse_workbook(buffer.getvalue())


# --- Загрузка ------------------------------------------------------------------


def test_загрузка_сохраняет_контрольную_сумму_и_число_правил(client, db_factory):
    headers = token(client, "root")
    response = upload(client, headers, EDITION_2026, "ЕКП 2026", note="первая редакция")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["sha256"] == hashlib.sha256(EDITION_2026).hexdigest()
    assert body["rule_count"] == 2
    assert body["is_active"] is False
    assert body["uploaded_by"] == "Администратор"
    assert body["warnings"] == []

    with db_factory() as db:
        stored = db.scalar(select(ClassifierVersion))
        assert stored.label == "ЕКП 2026"
        assert stored.note == "первая редакция"
        ekp = service.ekp_for_version(stored)
        assert len(ekp) == 2
        assert ekp.rule(FIRE_TRASH).incident_type == "пожар: мусор"


def test_повторная_загрузка_того_же_файла_отклоняется(client):
    headers = token(client, "root")
    assert upload(client, headers, EDITION_2026, "ЕКП 2026").status_code == 201
    again = upload(client, headers, EDITION_2026, "ЕКП 2026 повтор")
    assert again.status_code == 409
    assert "ЕКП 2026" in again.json()["detail"]


def test_занятое_обозначение_отклоняется(client):
    headers = token(client, "root")
    assert upload(client, headers, EDITION_2026, "ЕКП").status_code == 201
    assert upload(client, headers, EDITION_2027, "ЕКП").status_code == 409


def test_не_xlsx_и_битый_файл_отклоняются(client):
    headers = token(client, "root")
    wrong = client.post(
        "/api/admin/classifier/versions",
        files={"file": ("ekp.csv", b"a;b;c", "text/csv")},
        data={"label": "CSV"},
        headers=headers,
    )
    assert wrong.status_code == 415
    broken = upload(client, headers, b"PK\x03\x04" + "мусор".encode(), "Битый")
    assert broken.status_code == 422
    assert "не читается" in broken.json()["detail"]


def test_список_показывает_встроенную_редакцию_и_загруженные(client):
    headers = token(client, "root")
    upload(client, headers, EDITION_2026, "ЕКП 2026")
    body = client.get("/api/admin/classifier", headers=headers).json()
    assert body["builtin_rule_count"] == 1283
    assert body["builtin_active"] is True
    assert [v["label"] for v in body["versions"]] == ["ЕКП 2026"]


# --- Включение -----------------------------------------------------------------


def test_включение_переключает_ровно_одну_редакцию(client, db_factory):
    headers = token(client, "root")
    first = upload(client, headers, EDITION_2026, "ЕКП 2026").json()["id"]
    second = upload(client, headers, EDITION_2027, "ЕКП 2027").json()["id"]

    state = client.post(
        f"/api/admin/classifier/versions/{first}/activate", headers=headers
    ).json()
    assert state["builtin_active"] is False
    assert {v["id"]: v["is_active"] for v in state["versions"]} == {first: True, second: False}

    state = client.post(
        f"/api/admin/classifier/versions/{second}/activate", headers=headers
    ).json()
    assert {v["id"]: v["is_active"] for v in state["versions"]} == {first: False, second: True}

    with db_factory() as db:
        assert db.scalar(
            select(ClassifierVersion).where(ClassifierVersion.is_active.is_(True))
        ).id == second


def test_возврат_к_встроенной_выключает_все(client):
    headers = token(client, "root")
    version = upload(client, headers, EDITION_2026, "ЕКП 2026").json()["id"]
    client.post(f"/api/admin/classifier/versions/{version}/activate", headers=headers)

    state = client.post("/api/admin/classifier/builtin", headers=headers).json()
    assert state["builtin_active"] is True
    assert all(v["is_active"] is False for v in state["versions"])


def test_несуществующую_редакцию_включить_нельзя(client):
    headers = token(client, "root")
    assert (
        client.post("/api/admin/classifier/versions/999/activate", headers=headers).status_code
        == 404
    )


# --- Привязка занятия ----------------------------------------------------------


def test_новое_занятие_получает_действующую_редакцию(client, db_factory):
    admin = token(client, "root")
    teacher = token(client, "teacher")
    version = upload(client, admin, EDITION_2026, "ЕКП 2026").json()["id"]
    client.post(f"/api/admin/classifier/versions/{version}/activate", headers=admin)

    created = client.post(
        "/api/teacher/sessions", json={"title": "Занятие по новой редакции"}, headers=teacher
    ).json()
    assert created["classifier_version_label"] == "ЕКП 2026"

    with db_factory() as db:
        session = db.get(TrainingSession, created["id"])
        assert session.classifier_version_id == version
        assert service.ekp_for_session(session).rule(FIRE_TRASH).incident_type == "пожар: мусор"


def test_без_включённой_редакции_занятие_идёт_по_встроенной(client, db_factory):
    teacher = token(client, "teacher")
    created = client.post(
        "/api/teacher/sessions", json={"title": "Занятие по встроенной"}, headers=teacher
    ).json()
    assert created["classifier_version_label"] is None

    with db_factory() as db:
        session = db.get(TrainingSession, created["id"])
        assert session.classifier_version_id is None
        assert service.ekp_for_session(session) is get_ekp()
        assert len(service.current_ekp(db)) == 1283


def test_занятие_созданное_до_смены_редакции_остаётся_на_своей(client, db_factory):
    admin = token(client, "root")
    teacher = token(client, "teacher")
    old = upload(client, admin, EDITION_2026, "ЕКП 2026").json()["id"]
    new = upload(client, admin, EDITION_2027, "ЕКП 2027").json()["id"]

    client.post(f"/api/admin/classifier/versions/{old}/activate", headers=admin)
    earlier = client.post(
        "/api/teacher/sessions", json={"title": "Раннее занятие"}, headers=teacher
    ).json()
    client.post(f"/api/admin/classifier/versions/{new}/activate", headers=admin)
    later = client.post(
        "/api/teacher/sessions", json={"title": "Позднее занятие"}, headers=teacher
    ).json()

    assert earlier["classifier_version_label"] == "ЕКП 2026"
    assert later["classifier_version_label"] == "ЕКП 2027"
    with db_factory() as db:
        before = service.ekp_for_session(db.get(TrainingSession, earlier["id"]))
        after = service.ekp_for_session(db.get(TrainingSession, later["id"]))
    assert before.rule(FIRE_TRASH).incident_type == "пожар: мусор"
    assert after.rule(FIRE_TRASH).incident_type == "пожар: мусор (ред. 2027)"


def _operator_call(db_factory, session_id: int) -> int:
    """Вызов оператора 112 в указанном занятии: карточка на горящий мусор."""
    with db_factory() as db:
        service_row = db.scalar(select(DispatchService))
        teacher = db.scalar(select(User).where(User.login == "teacher"))
        student = db.scalar(select(User).where(User.login == "student"))
        scenario = Scenario(
            title="Горит мусор",
            mode=TrainingMode.OPERATOR,
            incident_type="пожар: мусор",
            ekp_rule_number=FIRE_TRASH,
            expected_outcome=CallOutcome.CLASSIFY,
            address="Москва",
            description="Горит контейнер",
            target_service=service_row,
            expected_primary_status="Принята",
            author=teacher,
        )
        session = db.get(TrainingSession, session_id)
        session.state = SessionState.ACTIVE
        attempt = Attempt(
            session=session,
            student=student,
            scenario=scenario,
            issued_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        )
        db.add_all([scenario, attempt])
        db.commit()
        return attempt.id


def test_оценка_вызова_идёт_по_редакции_занятия(client, db_factory):
    """Один и тот же ответ в двух занятиях разбирается по разным редакциям."""
    admin = token(client, "root")
    teacher = token(client, "teacher")
    student = token(client, "student")

    builtin_session = client.post(
        "/api/teacher/sessions", json={"title": "По встроенной"}, headers=teacher
    ).json()["id"]
    version = upload(client, admin, EDITION_2027, "ЕКП 2027").json()["id"]
    client.post(f"/api/admin/classifier/versions/{version}/activate", headers=admin)
    new_session = client.post(
        "/api/teacher/sessions", json={"title": "По новой"}, headers=teacher
    ).json()["id"]

    answer = {
        "group": FIRES,
        "path": ["на улице", "мусор", "дым"],
        "address": "Москва, двор",
        "description": "Горит мусорный контейнер",
    }
    by_builtin = client.post(
        f"/api/operator/calls/{_operator_call(db_factory, builtin_session)}/classify",
        json=answer,
        headers=student,
    ).json()
    by_new = client.post(
        f"/api/operator/calls/{_operator_call(db_factory, new_session)}/classify",
        json=answer,
        headers=student,
    ).json()

    assert by_builtin["classification"]["expected_incident_type"] == "пожар: мусор"
    assert by_new["classification"]["expected_incident_type"] == "пожар: мусор (ред. 2027)"
    # В новой редакции МВД оповещается по умолчанию, во встроенной — нет.
    assert "МВД" in by_new["classification"]["notified_services"]
    assert "МВД" not in by_builtin["classification"]["notified_services"]


def test_опросная_карта_вызова_строится_по_редакции_занятия(client, db_factory):
    admin = token(client, "root")
    teacher = token(client, "teacher")
    student = token(client, "student")
    version = upload(client, admin, EDITION_2027, "ЕКП 2027").json()["id"]
    client.post(f"/api/admin/classifier/versions/{version}/activate", headers=admin)
    session_id = client.post(
        "/api/teacher/sessions", json={"title": "По новой"}, headers=teacher
    ).json()["id"]
    attempt_id = _operator_call(db_factory, session_id)

    groups = client.get(f"/api/operator/groups?attempt_id={attempt_id}", headers=student).json()
    assert groups == [FIRES]
    options = client.get(
        f"/api/operator/options?attempt_id={attempt_id}&group={FIRES}&path=на улице|мусор",
        headers=student,
    ).json()
    assert {o["incident_type"] for o in options} == {
        "пожар: мусор (ред. 2027)", "задымление: мусор"
    }
    # Без вызова — справочный просмотр по действующей редакции; она та же.
    assert client.get("/api/operator/groups", headers=student).json() == [FIRES]


def test_каталог_преподавателя_берёт_действующую_редакцию(client):
    admin = token(client, "root")
    teacher = token(client, "teacher")
    assert len(client.get("/api/teacher/catalog", headers=teacher).json()["groups"]) == 23

    version = upload(client, admin, EDITION_2026, "ЕКП 2026").json()["id"]
    client.post(f"/api/admin/classifier/versions/{version}/activate", headers=admin)
    assert client.get("/api/teacher/catalog", headers=teacher).json()["groups"] == [FIRES]


# --- Журнал и права ------------------------------------------------------------


def test_загрузка_и_включение_попадают_в_журнал(client, db_factory):
    headers = token(client, "root")
    version = upload(client, headers, EDITION_2026, "ЕКП 2026").json()["id"]
    client.post(f"/api/admin/classifier/versions/{version}/activate", headers=headers)
    client.post("/api/admin/classifier/builtin", headers=headers)

    with db_factory() as db:
        events = {
            e.action: e
            for e in db.scalars(
                select(AuditEvent).where(AuditEvent.object_type == "classifier_version")
            ).all()
        }
    uploaded = events[AuditAction.CLASSIFIER_UPLOADED]
    assert uploaded.actor_login == "root"
    assert uploaded.object_id == version
    assert uploaded.detail["обозначение"] == "ЕКП 2026"
    assert uploaded.detail["правил"] == "2"
    assert events[AuditAction.CLASSIFIER_ACTIVATED].object_id == version
    assert events[AuditAction.CLASSIFIER_BUILTIN_RESTORED].detail["была включена"] == "ЕКП 2026"


def test_редакциями_управляет_только_администратор(client):
    for login in ("teacher", "student"):
        headers = token(client, login)
        assert client.get("/api/admin/classifier", headers=headers).status_code == 403
        assert upload(client, headers, EDITION_2026, "Чужая").status_code == 403
        assert (
            client.post("/api/admin/classifier/versions/1/activate", headers=headers).status_code
            == 403
        )
        assert client.post("/api/admin/classifier/builtin", headers=headers).status_code == 403
