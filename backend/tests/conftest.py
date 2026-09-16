"""Общие фикстуры: временная база и приложение с учебными данными."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_session
from app.core.security import hash_password
from app.main import app
from app.models.base import Base
from app.models.training import Attempt, Scenario, SessionState, TrainingSession
from app.models.user import DispatchService, Role, User
from app.services.response_status import ResponseStatus as S

PASSWORD = "pwd"


@pytest.fixture
def db_factory():
    # StaticPool — иначе каждое соединение открывало бы собственную пустую базу.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with factory() as db:
        service = DispatchService(
            name="ДДС района Чертаново Южное", ekp_name="Территориальные ОИВ"
        )
        users = {
            "root": User(
                login="root",
                full_name="Администратор",
                hashed_password=hash_password(PASSWORD),
                role=Role.ADMIN,
            ),
            "teacher": User(
                login="teacher",
                full_name="Преподаватель",
                hashed_password=hash_password(PASSWORD),
                role=Role.TEACHER,
            ),
            "student": User(
                login="student",
                full_name="Иванов И.И.",
                hashed_password=hash_password(PASSWORD),
                role=Role.STUDENT,
                service=service,
            ),
            "other": User(
                login="other",
                full_name="Петров П.П.",
                hashed_password=hash_password(PASSWORD),
                role=Role.STUDENT,
                service=service,
            ),
        }
        db.add(service)
        db.add_all(users.values())
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
            author=users["teacher"],
        )
        training = TrainingSession(
            title="Занятие 1",
            teacher=users["teacher"],
            state=SessionState.ACTIVE,
            deadline_seconds=30,
        )
        db.add_all([scenario, training])
        db.flush()
        db.add(
            Attempt(
                session=training,
                student=users["student"],
                scenario=scenario,
                issued_at=datetime.now(timezone.utc) - timedelta(seconds=5),
            )
        )
        db.commit()

    return factory


@pytest.fixture
def client(db_factory, monkeypatch):
    def override_session():
        with db_factory() as session:
            yield session

    monkeypatch.setattr("app.api.attempts.SessionLocal", db_factory)
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(client):
    """То же приложение: имя подчёркивает, что проверяются права администратора."""
    return client
