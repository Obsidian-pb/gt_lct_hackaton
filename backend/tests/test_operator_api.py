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


def test_разбор_объясняет_список_оповещения_по_признакам_вызова(client, db_factory):
    """Пострадавшие есть у вызова — скорая в списке, и разбор говорит почему."""
    attempt_id = make_call(db_factory, flags=["пострадавшие"])
    response = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={
            "outcome": "classify",
            "group": "Пожары и задымления",
            "path": ["на улице", "мусор", "открытое пламя"],
            "address": "Москва, ул. Кировоградская, д. 24",
            "description": "Горит контейнер, есть пострадавший",
            "flags": ["пострадавшие"],
        },
        headers=token(client, "student"),
    )
    assert response.status_code == 200, response.text
    classification = response.json()["classification"]
    # Список оповещения считается с признаками вызова — как на карточке диспетчера.
    assert "СМП" in classification["notified_services"]
    assert classification["missed_services"] == []
    assert classification["expected_flags"] == ["пострадавшие"]
    assert classification["chosen_flags"] == ["пострадавшие"]
    assert classification["missed_flags"] == []
    assert classification["extra_flags"] == []
    reasons = {r["service"]: r for r in classification["notification_reasons"]}
    assert reasons["СМП"]["notified"] is True
    assert "«пострадавшие»" in reasons["СМП"]["reason"]
    assert reasons["МЧС"]["notified"] is True
    assert "всегда" in reasons["МЧС"]["reason"]
    # Служба, которой не хватило признака, названа с подсказкой, а не пропущена молча.
    assert reasons["МОСГАЗ"]["notified"] is False
    assert "газификация" in reasons["МОСГАЗ"]["reason"]


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


# --- Признаки опросной карты -------------------------------------------------

RIGHT_CARD = {
    "outcome": "classify",
    "group": "Пожары и задымления",
    "path": ["на улице", "мусор", "открытое пламя"],
    "address": "Москва, ул. Кировоградская, д. 24",
    "description": "Горит мусорный контейнер",
}

FULL_PATH = {"group": "Пожары и задымления", "path": "на улице|мусор|открытое пламя"}


def test_отмеченные_признаки_сохраняются_и_видны_в_карточке(client, db_factory):
    attempt_id = make_call(db_factory, flags=["пострадавшие"])
    headers = token(client, "student")
    body = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={**RIGHT_CARD, "flags": ["пострадавшие", "пострадавшие"]},
        headers=headers,
    )
    assert body.status_code == 200, body.text
    # Повтор ключа не размножает признак.
    assert body.json()["classification"]["chosen_flags"] == ["пострадавшие"]
    card = client.get(f"/api/operator/calls/{attempt_id}", headers=headers).json()
    assert card["chosen_flags"] == ["пострадавшие"]


def test_пропущенный_признак_виден_в_разборе(client, db_factory):
    """Кнопка не нажата: разбор называет признак, службу и нарушение O14."""
    attempt_id = make_call(db_factory, flags=["пострадавшие"])
    body = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={**RIGHT_CARD, "flags": []},
        headers=token(client, "student"),
    )
    assert body.status_code == 200, body.text
    result = body.json()
    classification = result["classification"]
    assert classification["correct"] is True
    assert classification["missed_flags"] == ["пострадавшие"]
    assert "СМП" in classification["missed_services"]
    # Эталонный список и его обоснование по-прежнему с признаками вызова.
    assert "СМП" in classification["notified_services"]
    assert [v["code"] for v in result["violations"]] == ["O14"]
    assert result["violations"][0]["severity"] == "критическое"
    assert result["score"] < 1.0


def test_неизвестный_признак_отклоняется_с_перечнем_допустимых(client, db_factory):
    attempt_id = make_call(db_factory)
    headers = token(client, "student")
    body = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={**RIGHT_CARD, "flags": ["метеорит"]},
        headers=headers,
    )
    assert body.status_code == 422, body.text
    detail = body.json()["detail"]
    assert "метеорит" in detail
    assert "пострадавшие" in detail and "газификация" in detail
    # Отклонённая карточка не считается сданной.
    card = client.get(f"/api/operator/calls/{attempt_id}", headers=headers).json()
    assert card["finished"] is False


def test_передача_по_принадлежности_с_пустыми_признаками(client, db_factory):
    """Фронт шлёт `flags` всегда; при передаче вызова список пуст, и это не ошибка."""
    attempt_id = make_call(
        db_factory,
        ekp_rule_number=None,
        address="Тульская обл., г. Киреевск",
        expected_outcome=CallOutcome.REFER,
        referral_target="Тульская область",
    )
    body = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={
            "outcome": "refer",
            "referral_target": "Тульская область",
            "address": "Тульская обл., г. Киреевск",
            "description": "ДТП",
            "flags": [],
        },
        headers=token(client, "student"),
    )
    assert body.status_code == 200, body.text
    assert body.json()["violations"] == []


def test_кнопки_признаков_глобальные_всегда_а_правила_по_пути(client, db_factory):
    attempt_id = make_call(db_factory)
    headers = token(client, "student")

    # До выбора категории фронт запрашивает кнопки с пустыми group и path.
    empty = client.get(
        "/api/operator/flags", params={"group": "", "path": ""}, headers=headers
    )
    assert empty.status_code == 200, empty.text
    assert [f["key"] for f in empty.json()["global"]] == [
        "пострадавшие",
        "пострадавшие_не_на_месте",
        "нет_доступа",
    ]
    assert empty.json()["global"][0]["title"] == "Пострадавшие"
    assert empty.json()["rule"] == []

    # Путь не доведён до правила — признаков правила ещё нет.
    partial = client.get(
        "/api/operator/flags",
        params={"attempt_id": attempt_id, "group": "Пожары и задымления", "path": "на улице"},
        headers=headers,
    ).json()
    assert len(partial["global"]) == 3
    assert partial["rule"] == []

    full = client.get(
        "/api/operator/flags", params={"attempt_id": attempt_id, **FULL_PATH}, headers=headers
    ).json()
    keys = [f["key"] for f in full["rule"]]
    assert "газификация" in keys
    assert "пострадавшие" not in keys
    titles = {f["key"]: f["title"] for f in full["rule"]}
    assert titles["газификация"] == "Проведена ли газификация"


def test_предпросмотр_списка_оповещения_по_выбору_оператора(client, db_factory):
    attempt_id = make_call(db_factory, flags=["пострадавшие"])
    headers = token(client, "student")

    # Без доведённого пути и с пустыми признаками показывать нечего — и это 200.
    empty = client.get(
        "/api/operator/preview",
        params={"attempt_id": attempt_id, "group": "Пожары и задымления", "path": "на улице", "flags": ""},
        headers=headers,
    )
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"incident_type": None, "services": []}
    nothing = client.get(
        "/api/operator/preview", params={"group": "", "path": "", "flags": ""}, headers=headers
    )
    assert nothing.status_code == 200, nothing.text
    assert nothing.json() == {"incident_type": None, "services": []}

    path = {"attempt_id": attempt_id, **FULL_PATH}
    # Признаки вызова у попытки есть, но оператор их не отметил — в полосе служб
    # скорой нет: предпросмотр не подсказывает эталон.
    plain = client.get("/api/operator/preview", params=path, headers=headers).json()
    assert plain["incident_type"] == "пожар: мусор"
    services = {s["service"]: s for s in plain["services"]}
    assert "МЧС" in services
    assert "СМП" not in services
    assert all(s["notified"] for s in plain["services"])

    marked = client.get(
        "/api/operator/preview", params={**path, "flags": "пострадавшие"}, headers=headers
    ).json()
    services = {s["service"]: s for s in marked["services"]}
    assert services["СМП"]["notified"] is True
    assert "«пострадавшие»" in services["СМП"]["reason"]
    assert all(s["notified"] for s in marked["services"])


def test_без_разметки_признаков_выбор_оператора_не_сверяется(client, db_factory):
    """Сценарий из билета без признаков: оператор отметил пострадавших — это не ошибка."""
    attempt_id = make_call(db_factory)  # flags у сценария не заданы
    response = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={
            "outcome": "classify",
            "group": "Пожары и задымления",
            "path": ["на улице", "мусор", "открытое пламя"],
            "address": "Москва, ул. Кировоградская, д. 24",
            "description": "Горит контейнер",
            "flags": ["пострадавшие"],
        },
        headers=token(client, "student"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    classification = body["classification"]
    assert classification["flags_checked"] is False
    assert classification["chosen_flags"] == ["пострадавшие"]
    assert classification["extra_flags"] == [] and classification["missed_flags"] == []
    assert classification["extra_services"] == []
    assert not any(v["code"] in ("O14", "O15") for v in body["violations"])
    # Отметка сохранена и видна в карточке вызова.
    call = client.get(f"/api/operator/calls/{attempt_id}", headers=token(client, "student")).json()
    assert call["chosen_flags"] == ["пострадавшие"]
