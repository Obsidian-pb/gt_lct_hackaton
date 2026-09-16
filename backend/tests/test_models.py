"""Схема должна разворачиваться на любой из основных СУБД — проверяем на SQLite."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.training import Attempt, Scenario, SessionState, StatusEvent, TrainingSession
from app.models.user import DispatchService, Role, User


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_схема_разворачивается(session):
    assert Base.metadata.tables.keys() >= {
        "app_user",
        "dispatch_service",
        "scenario",
        "training_session",
        "attempt",
        "status_event",
        "evaluation",
    }


def test_полный_цикл_занятия(session):
    service = DispatchService(name="ДДС района Чертаново Южное")
    teacher = User(
        login="teacher", full_name="Преподаватель", hashed_password="x", role=Role.TEACHER
    )
    student = User(
        login="student",
        full_name="Обучающийся",
        hashed_password="x",
        role=Role.STUDENT,
        service=service,
    )
    session.add_all([service, teacher, student])
    session.flush()

    scenario = Scenario(
        title="Застревание в лифте",
        incident_type="застревание в лифте",
        ekp_rule_number=1010101,
        address="Москва, ул. Берзарина, д. 21",
        description="Застряли в лифте, медицинская помощь не требуется",
        target_service=service,
        expected_primary_status="Не принята",
        is_profile=False,
        required_comment_points=["информация передана в диспетчерскую «Практика»"],
        author=teacher,
    )
    training = TrainingSession(
        title="Занятие 1", teacher=teacher, state=SessionState.ACTIVE
    )
    session.add_all([scenario, training])
    session.flush()

    issued = datetime.now(timezone.utc)
    attempt = Attempt(
        session=training, student=student, scenario=scenario, issued_at=issued
    )
    session.add(attempt)
    session.flush()
    session.add(
        StatusEvent(
            attempt=attempt,
            status="Не принята",
            comment="Не обслуживаем, информация передана в диспетчерскую «Практика»",
            elapsed_seconds=18.4,
        )
    )
    session.commit()

    stored = session.scalar(select(Attempt))
    assert stored.scenario.is_approved is False
    assert len(stored.events) == 1
    assert stored.events[0].elapsed_seconds == pytest.approx(18.4)
    assert stored.student.service.name == "ДДС района Чертаново Южное"


def test_сценарий_считается_утверждённым_после_подтверждения(session):
    teacher = User(login="t", full_name="Т", hashed_password="x", role=Role.TEACHER)
    service = DispatchService(name="Мослифт")
    session.add_all([teacher, service])
    session.flush()
    scenario = Scenario(
        title="s",
        incident_type="t",
        address="a",
        description="d",
        target_service=service,
        expected_primary_status="Принята",
        author=teacher,
    )
    session.add(scenario)
    session.flush()

    assert scenario.is_approved is False
    scenario.approved_by = teacher
    scenario.approved_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    assert scenario.is_approved is True
