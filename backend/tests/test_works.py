"""Сквозной список работ у преподавателя: фильтры, страницы, справочники."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.models.training import (
    Attempt,
    Evaluation,
    Scenario,
    SessionState,
    TrainingMode,
    TrainingSession,
)
from app.models.user import DispatchService, Role, User
from app.services.response_status import ResponseStatus as S


def token(client: TestClient, login: str) -> dict:
    response = client.post("/api/auth/token", data={"username": login, "password": "pwd"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def violation(code: str) -> dict:
    return {"code": code, "title": "", "severity": "", "detail": "", "example": ""}


NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def filled(db_factory):
    """Работы двух обучающихся в двух занятиях разных режимов.

    Диспетчер (student, «Занятие 1», порог 0.7): три завершённые работы —
    зачтённая, проваленная по баллу, проваленная критическим нарушением
    при высоком балле. Оператор (other, «Вызовы 112»): одна зачтённая работа
    неделей раньше. Незавершённая карточка из общих фикстур остаётся.
    Третий обучающийся и пустое занятие — чтобы справочники фильтров
    было с чем сравнить.
    """
    with db_factory() as db:
        student = db.query(User).filter_by(login="student").one()
        other = db.query(User).filter_by(login="other").one()
        teacher = db.query(User).filter_by(login="teacher").one()
        service = db.query(DispatchService).one()
        dispatcher_session = db.query(TrainingSession).one()
        lift = db.query(Scenario).one()

        db.add(
            User(
                login="third",
                full_name="Сидоров С.С.",
                hashed_password=hash_password("pwd"),
                role=Role.STUDENT,
            )
        )
        db.add(
            TrainingSession(
                title="Пустое занятие", teacher=teacher, state=SessionState.DRAFT,
                pickup_deadline_seconds=30, handling_deadline_seconds=180,
            )
        )

        fire = Scenario(
            title="Пожар в квартире",
            mode=TrainingMode.OPERATOR,
            incident_type="Пожар в жилом доме",
            ekp_rule_number=1010101,
            address="Москва, ул. Кировоградская, д. 24",
            description="Горит кухня на третьем этаже",
            caller="Иванов И. И., 916-126-34-71",
            target_service=service,
            expected_primary_status=str(S.ACCEPTED),
            deadline_seconds=180,
            author=teacher,
        )
        operator_session = TrainingSession(
            title="Вызовы 112",
            mode=TrainingMode.OPERATOR,
            teacher=teacher,
            state=SessionState.FINISHED,
            pickup_deadline_seconds=30,
            handling_deadline_seconds=180,
        )

        works = [
            # (обучающийся, занятие, сценарий, завершена, балл, нарушения)
            (student, dispatcher_session, lift, NOW - timedelta(hours=2), 0.9, []),
            (student, dispatcher_session, lift, NOW - timedelta(hours=1), 0.5, ["V4"]),
            (student, dispatcher_session, lift, NOW, 0.95, ["V8"]),
            (other, operator_session, fire, NOW - timedelta(days=7), 0.8, []),
        ]
        for who, session, scenario, finished_at, score, codes in works:
            db.add(
                Attempt(
                    session=session,
                    student=who,
                    scenario=scenario,
                    issued_at=finished_at - timedelta(minutes=3),
                    opened_at=finished_at - timedelta(minutes=2),
                    finished_at=finished_at,
                    evaluation=Evaluation(
                        score=score,
                        criteria={},
                        violations=[violation(c) for c in codes],
                        llm_pending=False,
                    ),
                )
            )
        db.commit()
    return db_factory


def works(client, **params) -> dict:
    response = client.get("/api/teacher/works", params=params, headers=token(client, "teacher"))
    assert response.status_code == 200, response.text
    return response.json()


def test_в_списке_только_завершённые_новые_сверху(client, filled):
    body = works(client)
    assert body["total"] == 4
    assert len(body["items"]) == 4
    # Незавершённая карточка из общих фикстур — под номером 1 — не показана.
    assert 1 not in [w["attempt_id"] for w in body["items"]]
    dates = [w["finished_at"] for w in body["items"]]
    assert dates == sorted(dates, reverse=True)


def test_строка_несёт_занятие_режим_и_зачёт(client, filled):
    latest = works(client)["items"][0]
    assert latest["session_title"] == "Занятие 1"
    assert latest["mode"] == "dispatcher"
    assert latest["student_name"] == "Иванов И.И."
    assert latest["scenario_title"] == "Застревание в лифте"
    # Балл 0.95 выше порога, но V8 — критическое: работа не зачтена.
    assert latest["critical"] == 1
    assert latest["passed"] is False


def test_фильтр_по_обучающемуся(client, filled):
    with filled() as db:
        other_id = db.query(User).filter_by(login="other").one().id
    body = works(client, student_id=other_id)
    assert body["total"] == 1
    assert body["items"][0]["student_name"] == "Петров П.П."


def test_фильтр_по_режиму(client, filled):
    assert works(client, mode="operator")["total"] == 1
    assert works(client, mode="dispatcher")["total"] == 3


def test_неизвестный_режим_отклоняется(client, filled):
    response = client.get(
        "/api/teacher/works", params={"mode": "pilot"}, headers=token(client, "teacher")
    )
    assert response.status_code == 422


def test_фильтр_по_зачёту(client, filled):
    passed = works(client, passed="true")
    failed = works(client, passed="false")
    assert passed["total"] == 2
    assert all(w["passed"] is True for w in passed["items"])
    assert failed["total"] == 2
    assert sorted(w["score"] for w in failed["items"]) == [0.5, 0.95]


def test_фильтр_по_занятию(client, filled):
    with filled() as db:
        operator_id = db.query(TrainingSession).filter_by(title="Вызовы 112").one().id
    body = works(client, session_id=operator_id)
    assert body["total"] == 1
    assert body["items"][0]["session_id"] == operator_id


def test_фильтр_по_периоду_включает_границы_суток(client, filled):
    day = NOW.date().isoformat()
    assert works(client, date_from=day, date_to=day)["total"] == 3
    assert works(client, date_to=(NOW - timedelta(days=1)).date().isoformat())["total"] == 1
    assert works(client, date_from=(NOW + timedelta(days=1)).date().isoformat())["total"] == 0


def test_поиск_без_учёта_регистра_по_сценарию_типу_и_адресу(client, filled):
    assert works(client, q="ЛИФТ")["total"] == 3
    assert works(client, q="жилом доме")["total"] == 1
    assert works(client, q="кировоградская")["total"] == 1
    assert works(client, q="наводнение")["total"] == 0


def test_страницы_и_общее_число(client, filled):
    first = works(client, limit=3)
    second = works(client, limit=3, offset=3)
    assert first["total"] == second["total"] == 4
    assert len(first["items"]) == 3
    assert len(second["items"]) == 1
    ids = [w["attempt_id"] for w in first["items"] + second["items"]]
    assert len(set(ids)) == 4


def test_предел_страницы_ограничен(client, filled):
    response = client.get(
        "/api/teacher/works", params={"limit": 500}, headers=token(client, "teacher")
    )
    assert response.status_code == 422


def test_справочники_фильтров_только_с_завершёнными_работами(client, filled):
    body = client.get("/api/teacher/works/filters", headers=token(client, "teacher")).json()
    assert [s["full_name"] for s in body["students"]] == ["Иванов И.И.", "Петров П.П."]
    assert {s["title"]: s["mode"] for s in body["sessions"]} == {
        "Занятие 1": "dispatcher",
        "Вызовы 112": "operator",
    }


def test_без_работ_справочники_пусты(client):
    body = client.get("/api/teacher/works/filters", headers=token(client, "teacher")).json()
    assert body == {"students": [], "sessions": []}
    assert works(client) == {"items": [], "total": 0}


@pytest.mark.parametrize("login", ["student", "root"])
@pytest.mark.parametrize("path", ["/api/teacher/works", "/api/teacher/works/filters"])
def test_список_работ_закрыт_обучающемуся_и_администратору(client, filled, login, path):
    """Администратору — тоже: в работах персональные данные обучающихся."""
    response = client.get(path, headers=token(client, login))
    assert response.status_code == 403
