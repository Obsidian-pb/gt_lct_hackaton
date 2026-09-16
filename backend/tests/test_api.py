"""Сквозная проверка API: вход, работа с карточкой, получение оценки."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.attempts import run_llm_review
from app.core.db import get_session
from app.core.security import hash_password
from app.llm.base import CommentReview
from app.main import app
from app.models.base import Base
from app.models.training import Attempt, Scenario, SessionState, TrainingSession
from app.models.user import DispatchService, Role, User
from app.services.response_status import ResponseStatus as S


@pytest.fixture
def client(monkeypatch):
    # StaticPool — иначе каждое соединение открывало бы собственную пустую базу.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with factory() as db:
        service = DispatchService(name="ДДС района Чертаново Южное")
        teacher = User(
            login="teacher", full_name="Т", hashed_password=hash_password("pwd"), role=Role.TEACHER
        )
        student = User(
            login="student",
            full_name="Иванов И.И.",
            hashed_password=hash_password("pwd"),
            role=Role.STUDENT,
            service=service,
        )
        other = User(
            login="other",
            full_name="Петров П.П.",
            hashed_password=hash_password("pwd"),
            role=Role.STUDENT,
            service=service,
        )
        db.add_all([service, teacher, student, other])
        db.flush()

        scenario = Scenario(
            title="Застревание в лифте",
            incident_type="застревание в лифте",
            ekp_rule_number=1010101,
            flags=[],
            address="Москва, ул. Берзарина, д. 21, под. 3",
            description="Застряли в лифте, медицинская помощь не требуется",
            caller="Ким Олег Юрьевич, 916-126-34-71",
            target_service=service,
            expected_primary_status=str(S.REJECTED),
            is_profile=False,
            required_comment_points=["информация передана в диспетчерскую «Практика»"],
            author=teacher,
        )
        training = TrainingSession(
            title="Занятие 1", teacher=teacher, state=SessionState.ACTIVE, deadline_seconds=30
        )
        db.add_all([scenario, training])
        db.flush()
        db.add(
            Attempt(
                session=training,
                student=student,
                scenario=scenario,
                issued_at=datetime.now(timezone.utc) - timedelta(seconds=5),
            )
        )
        db.commit()

    def override_session():
        with factory() as session:
            yield session

    monkeypatch.setattr("app.api.attempts.SessionLocal", factory)
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def token(client: TestClient, login: str) -> dict:
    response = client.post("/api/auth/token", data={"username": login, "password": "pwd"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_здоровье_сервиса(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["ekp_rules"] == 1283


def test_вход_с_неверным_паролем_отклоняется(client):
    response = client.post("/api/auth/token", data={"username": "student", "password": "nope"})
    assert response.status_code == 401


def test_без_токена_доступа_нет(client):
    assert client.get("/api/attempts/my").status_code == 401


def test_карточка_содержит_список_оповещения_из_екп(client):
    headers = token(client, "student")
    cards = client.get("/api/attempts/my", headers=headers).json()
    assert len(cards) == 1
    card = cards[0]
    assert card["address"].startswith("Москва, ул. Берзарина")
    assert card["available_statuses"] == [str(S.ACCEPTED), str(S.REJECTED)]
    assert "Классификатор МЧС" in card["notified_services"]


def test_обучающийся_не_видит_чужую_карточку(client):
    headers = token(client, "other")
    assert client.get("/api/attempts/my", headers=headers).json() == []
    assert client.get("/api/attempts/1", headers=headers).status_code == 403


def test_недопустимый_статус_отклоняется(client):
    headers = token(client, "student")
    response = client.post(
        "/api/attempts/1/status", json={"status": str(S.ARRIVED)}, headers=headers
    )
    assert response.status_code == 409
    assert "нельзя перейти" in response.json()["detail"]


def test_неизвестный_статус_отклоняется(client):
    headers = token(client, "student")
    response = client.post("/api/attempts/1/status", json={"status": "Съел"}, headers=headers)
    assert response.status_code == 422


def test_полный_цикл_обработки_карточки(client):
    headers = token(client, "student")
    client.post("/api/attempts/1/open", headers=headers)

    card = client.post(
        "/api/attempts/1/status",
        json={
            "status": str(S.REJECTED),
            "comment": "Не обслуживаем, информация передана в диспетчерскую «Практика»",
        },
        headers=headers,
    ).json()
    assert card["current_status"] == str(S.REJECTED)
    assert card["available_statuses"] == [str(S.ACCEPTED)]

    evaluation = client.post("/api/attempts/1/finish", headers=headers).json()
    assert evaluation["violations"] == []
    assert evaluation["score"] == 1.0
    # Детерминированная часть готова сразу, смысловая проверка ещё идёт.
    assert evaluation["llm_pending"] is True


@pytest.mark.asyncio
async def test_фоновая_оценка_дописывает_пропущенный_пункт_и_идемпотентна(client, monkeypatch):
    class FakeProvider:
        name = "fake"

        async def review_comment(self, *, comment, required_points, context):
            return CommentReview(
                missing_points=list(required_points), summary="проверено", available=True
            )

    monkeypatch.setattr("app.api.attempts.get_llm_provider", lambda: FakeProvider())
    headers = token(client, "student")
    client.post(
        "/api/attempts/1/status",
        json={"status": str(S.REJECTED), "comment": "Не обслуживаем"},
        headers=headers,
    )
    client.post("/api/attempts/1/finish", headers=headers)

    await run_llm_review(1)

    evaluation = client.get("/api/attempts/1/evaluation", headers=headers).json()
    assert evaluation["llm_pending"] is False
    assert [v["code"] for v in evaluation["violations"]] == ["V5"]
    assert "Практика" in evaluation["violations"][0]["detail"]
    assert evaluation["score"] < 1.0
