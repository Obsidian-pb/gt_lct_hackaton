"""Приём вызова через API: исход обращения от интерфейса до разбора."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.models.training import (
    Attempt,
    CallOutcome,
    Scenario,
    SessionState,
    TrainingMode,
    TrainingSession,
)
from app.models.user import DispatchService, User
from app.services.response_status import ResponseStatus as S

FIRE_TRASH = 1010101


def token(client: TestClient, login: str) -> dict:
    response = client.post("/api/auth/token", data={"username": login, "password": "pwd"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def make_call(db_factory, **scenario_fields) -> int:
    """Заводит вызов оператора 112 и возвращает номер попытки."""
    with db_factory() as db:
        student = db.query(User).filter_by(login="student").one()
        teacher = db.query(User).filter_by(login="teacher").one()
        service = db.query(DispatchService).one()
        defaults = dict(
            title="Учебный вызов",
            mode=TrainingMode.OPERATOR,
            incident_type="",
            ekp_rule_number=FIRE_TRASH,
            address="Москва, ул. Кировоградская, д. 24",
            description="Горит мусорный контейнер во дворе",
            caller="Иванов И. И., 916-126-34-71",
            target_service=service,
            expected_primary_status=str(S.ACCEPTED),
            deadline_seconds=180,
            author=teacher,
        )
        scenario = Scenario(**{**defaults, **scenario_fields})
        session = TrainingSession(
            title="Занятие 112",
            mode=TrainingMode.OPERATOR,
            teacher=teacher,
            state=SessionState.ACTIVE,
            pickup_deadline_seconds=30,
            handling_deadline_seconds=180,
        )
        attempt = Attempt(
            session=session,
            student=student,
            scenario=scenario,
            issued_at=datetime.now(timezone.utc) - timedelta(seconds=20),
        )
        db.add_all([scenario, session, attempt])
        db.commit()
        return attempt.id


def test_чужой_регион_передан_по_принадлежности(client, db_factory):
    attempt_id = make_call(
        db_factory,
        title="Билет 19, вызов 1",
        ekp_rule_number=None,
        address="Тульская обл., дорога от Киреевска в сторону Октябрьского",
        expected_outcome=CallOutcome.REFER,
        referral_target="Тульская область",
    )
    headers = token(client, "student")
    body = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={
            "outcome": "refer",
            "referral_target": "Тульская область",
            "address": "Тульская обл., дорога от Киреевска",
            "description": "Съезд автомобиля в кювет",
        },
        headers=headers,
    )
    assert body.status_code == 200, body.text
    result = body.json()
    assert result["violations"] == []
    assert result["score"] == 1.0
    assert result["expected_outcome"] == "refer"
    assert result["chosen_outcome"] == "refer"


def test_сценарий_без_правила_принимается_если_классифицировать_не_надо(client, db_factory):
    """Раньше такой вызов отвергался: правило классификатора было обязательным."""
    attempt_id = make_call(
        db_factory,
        ekp_rule_number=None,
        expected_outcome=CallOutcome.REJECT,
    )
    body = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={"outcome": "reject", "address": "Москва, Сущевский Вал, д. 5", "description": "Ссора с продавцом"},
        headers=token(client, "student"),
    )
    assert body.status_code == 200, body.text
    assert body.json()["violations"] == []


def test_чужой_регион_классифицирован_как_московский(client, db_factory):
    attempt_id = make_call(
        db_factory,
        ekp_rule_number=None,
        expected_outcome=CallOutcome.REFER,
        referral_target="Московская область",
    )
    body = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={
            "outcome": "classify",
            "group": "Пожары и задымления",
            "path": ["на улице", "мусор", "открытое пламя"],
            "address": "Балашиха, Мирской проезд, д. 16",
            "description": "Горит мусор",
        },
        headers=token(client, "student"),
    )
    assert body.status_code == 200, body.text
    result = body.json()
    assert [v["code"] for v in result["violations"]] == ["O7"]
    assert result["score"] == 0.0
    assert result["expected_referral_target"] == "Московская область"


def test_московское_происшествие_нельзя_передать_на_сторону(client, db_factory):
    attempt_id = make_call(db_factory)
    body = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={
            "outcome": "refer",
            "referral_target": "Московская область",
            "address": "Москва, ул. Кировоградская, д. 24",
            "description": "Горит мусор",
        },
        headers=token(client, "student"),
    )
    assert body.status_code == 200, body.text
    assert [v["code"] for v in body.json()["violations"]] == ["O8"]


def test_выбранный_исход_виден_в_карточке_вызова(client, db_factory):
    attempt_id = make_call(
        db_factory, ekp_rule_number=None, expected_outcome=CallOutcome.REJECT
    )
    headers = token(client, "student")
    client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={"outcome": "reject", "address": "Москва", "description": "Не происшествие"},
        headers=headers,
    )
    card = client.get(f"/api/operator/calls/{attempt_id}", headers=headers).json()
    assert card["chosen_outcome"] == "reject"
    assert card["finished"] is True


def test_прежний_запрос_без_исхода_работает_как_классификация(client, db_factory):
    """Совместимость: интерфейс, не знающий про исходы, продолжает работать."""
    attempt_id = make_call(db_factory)
    body = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={
            "group": "Пожары и задымления",
            "path": ["на улице", "мусор", "открытое пламя"],
            "address": "Москва, ул. Кировоградская, д. 24",
            "description": "Горит мусорный контейнер",
        },
        headers=token(client, "student"),
    )
    assert body.status_code == 200, body.text
    assert body.json()["score"] == 1.0
