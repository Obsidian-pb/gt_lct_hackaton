"""Сценарии работы с карточкой на АРМ-112."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.training import Attempt, CardStatus, Scenario, TrainingSession
from app.models.user import DispatchService, Role, User
from app.services.attempts import (
    AttemptError,
    available_statuses,
    build_evaluation,
    finish,
    open_card,
    record_status,
)
from app.services.response_status import ResponseStatus as S

ISSUED = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return ISSUED + timedelta(seconds=seconds)


@pytest.fixture
def attempt():
    service = DispatchService(name="ДДС района")
    teacher = User(login="t", full_name="Т", hashed_password="x", role=Role.TEACHER)
    student = User(
        login="s", full_name="С", hashed_password="x", role=Role.STUDENT, service=service
    )
    scenario = Scenario(
        title="Застревание в лифте",
        incident_type="застревание в лифте",
        address="Москва, ул. Берзарина, д. 21",
        description="Застряли в лифте, медицинская помощь не требуется",
        target_service=service,
        expected_primary_status=str(S.REJECTED),
        is_profile=False,
        required_comment_points=["информация передана в диспетчерскую «Практика»"],
        author=teacher,
    )
    session = TrainingSession(title="Занятие", teacher=teacher, deadline_seconds=30)
    return Attempt(session=session, student=student, scenario=scenario, issued_at=ISSUED)


def test_вначале_доступны_только_первичные_статусы(attempt):
    assert available_statuses(attempt) == [S.ACCEPTED, S.REJECTED]


def test_норматив_считается_от_направления_карточки_а_не_от_открытия(attempt):
    """Открыть карточку позже не значит получить больше времени на ответ."""
    open_card(attempt, now=at(20))
    event = record_status(attempt, S.ACCEPTED, now=at(25))
    assert attempt.opened_at == at(20)
    assert event.elapsed_seconds == pytest.approx(25.0)


def test_недопустимый_переход_отклоняется(attempt):
    """В настоящем АРМ-112 такой статус нельзя выбрать в выпадающем списке."""
    with pytest.raises(AttemptError, match="нельзя перейти"):
        record_status(attempt, S.ARRIVED, now=at(5))


def test_статус_без_комментария_принимается_и_оценивается(attempt):
    """Система не требует комментарий принудительно — это и есть нарушение V4."""
    record_status(attempt, S.REJECTED, comment=None, now=at(12))
    evaluation = build_evaluation(attempt)
    assert [v["code"] for v in evaluation.violations] == ["V4"]
    assert evaluation.llm_pending is False


def test_образцовая_обработка_без_нарушений(attempt):
    record_status(
        attempt,
        S.REJECTED,
        comment="Не обслуживаем, информация передана в диспетчерскую «Практика»",
        now=at(14),
    )
    evaluation = build_evaluation(attempt)
    assert evaluation.violations == []
    assert evaluation.score == 1.0
    # Комментарий есть и эталон требует проверки смысла — ждём LLM.
    assert evaluation.llm_pending is True


def test_опоздание_фиксируется(attempt):
    record_status(attempt, S.REJECTED, comment="не обслуживаем", now=at(41))
    evaluation = build_evaluation(attempt)
    assert [v["code"] for v in evaluation.violations] == ["V1"]
    assert "11 с" in evaluation.violations[0]["detail"]


def test_завершение_работ_закрывает_карточку(attempt):
    record_status(attempt, S.ACCEPTED, now=at(10))
    record_status(attempt, S.WORK_COMPLETED, comment="течь устранена", now=at(600))
    assert attempt.finished_at == at(600)
    assert attempt.card_status is CardStatus.COMPLETED
    with pytest.raises(AttemptError, match="завершена"):
        record_status(attempt, S.ARRIVED, now=at(700))


def test_бездействие_переводит_карточку_в_не_оповещено(attempt):
    finish(attempt, now=at(120))
    assert attempt.card_status is CardStatus.NOT_NOTIFIED
    evaluation = build_evaluation(attempt)
    assert [v["code"] for v in evaluation.violations] == ["V1"]


def test_исправление_ошибочного_не_принята(attempt):
    """Памятка: ошибочное «Не принята» исправляется переходом в «Принята»."""
    record_status(attempt, S.REJECTED, comment="не в компетенции", now=at(10))
    assert available_statuses(attempt) == [S.ACCEPTED]
    record_status(attempt, S.ACCEPTED, now=at(40))
    assert attempt.card_status is CardStatus.REGISTERED
