"""Работа обучающегося с карточкой происшествия.

Поведение намеренно повторяет настоящий АРМ-112:
  * список статусов последовательный, поэтому недопустимый переход отклоняется —
    в реальной программе его нельзя выбрать физически;
  * комментарий при этом НЕ требуется принудительно. Именно поэтому «нет
    комментария к статусу "Не принята"» числится в памятке отдельным типом
    нарушения — обучающийся должен иметь возможность эту ошибку совершить,
    иначе разбирать будет нечего.
"""

from __future__ import annotations

from datetime import datetime

from app.models.base import as_utc, utcnow
from app.models.training import Attempt, CardStatus, Evaluation, StatusEvent
from app.services.evaluation import Assessment, Expectation
from app.services.evaluation import StatusEvent as EvalEvent
from app.services.evaluation import evaluate
from app.services.response_status import PRIMARY, TERMINAL, ResponseStatus, check_transition


class AttemptError(RuntimeError):
    pass


def current_status(attempt: Attempt) -> ResponseStatus | None:
    if not attempt.events:
        return None
    last = max(attempt.events, key=lambda e: e.elapsed_seconds)
    return ResponseStatus(last.status)


def available_statuses(attempt: Attempt) -> list[ResponseStatus]:
    from app.services.response_status import available_transitions

    return list(available_transitions(current_status(attempt)))


def open_card(attempt: Attempt, now: datetime | None = None) -> Attempt:
    """Взятие карточки в работу: статус «Получена службой».

    С этого момента начинается отсчёт норматива обработки, а разрыв между
    поступлением вызова и открытием — это и есть время реакции, на которое
    отведено 30 секунд.
    """
    if attempt.opened_at is None:
        attempt.opened_at = now or utcnow()
    return attempt


def record_status(
    attempt: Attempt,
    status: ResponseStatus,
    comment: str | None = None,
    now: datetime | None = None,
) -> StatusEvent:
    if attempt.finished_at is not None:
        raise AttemptError("Работа с карточкой завершена")

    check = check_transition(current_status(attempt), status, require_comment=False)
    if not check.allowed:
        raise AttemptError(check.reason or "Недопустимый переход")

    moment = now or utcnow()
    event = StatusEvent(
        status=str(status),
        comment=(comment or "").strip() or None,
        elapsed_seconds=(moment - as_utc(attempt.issued_at)).total_seconds(),
    )
    # Добавляем через коллекцию родителя, а не присваиванием event.attempt:
    # в SQLAlchemy 2.0 каскад save-update через backref больше не работает,
    # и событие не попало бы в сессию.
    attempt.events.append(event)

    if status in TERMINAL:
        attempt.finished_at = moment
    attempt.card_status = _card_status(attempt, status)
    return event


def _card_status(attempt: Attempt, status: ResponseStatus) -> CardStatus:
    """Статус карточки глазами отдела контроля (раздел «Статусы карточки»)."""
    if status is ResponseStatus.WORK_COMPLETED:
        return CardStatus.COMPLETED
    if status is ResponseStatus.WORK_REFUSED:
        return CardStatus.REFUSED
    if status is ResponseStatus.REJECTED:
        return CardStatus.REFUSED
    return CardStatus.REGISTERED


def finish(attempt: Attempt, now: datetime | None = None) -> Attempt:
    """Завершает попытку — например, когда преподаватель закончил занятие."""
    if attempt.finished_at is None:
        attempt.finished_at = now or utcnow()
    if not any(ResponseStatus(e.status) in PRIMARY for e in attempt.events):
        # Отсутствие первичного статуса переводит карточку в «Не оповещено».
        attempt.card_status = CardStatus.NOT_NOTIFIED
    return attempt


def expectation_for(attempt: Attempt) -> Expectation:
    scenario = attempt.scenario
    session = attempt.session
    return Expectation(
        primary_status=ResponseStatus(scenario.expected_primary_status),
        is_profile=scenario.is_profile,
        pickup_deadline_seconds=session.pickup_deadline_seconds,
        handling_deadline_seconds=session.handling_deadline_seconds,
        required_comment_points=tuple(scenario.required_comment_points or ()),
        expects_progress_statuses=scenario.expects_progress_statuses,
    )


def timings(attempt: Attempt) -> tuple[float | None, float | None]:
    """Секунды до взятия карточки в работу и длительность обработки.

    Взятие в работу — от поступления вызова до открытия карточки.
    Обработка — от открытия до завершения: время, пока карточка занимала
    внимание диспетчера и мешала взяться за другие вызовы.
    """
    if attempt.opened_at is None:
        return None, None
    pickup = (as_utc(attempt.opened_at) - as_utc(attempt.issued_at)).total_seconds()
    handling = (
        (as_utc(attempt.finished_at) - as_utc(attempt.opened_at)).total_seconds()
        if attempt.finished_at is not None
        else None
    )
    return pickup, handling


def assess(attempt: Attempt) -> Assessment:
    events = [
        EvalEvent(
            status=ResponseStatus(e.status),
            elapsed_seconds=e.elapsed_seconds,
            comment=e.comment,
        )
        for e in attempt.events
    ]
    pickup, handling = timings(attempt)
    return evaluate(events, expectation_for(attempt), pickup, handling)


def build_evaluation(attempt: Attempt) -> Evaluation:
    """Сохраняет детерминированную часть оценки. Поля LLM дозаполняются фоном."""
    assessment = assess(attempt)
    needs_llm = bool(attempt.scenario.required_comment_points) and any(
        e.comment for e in attempt.events
    )
    return Evaluation(
        attempt=attempt,
        score=assessment.score,
        criteria={str(k): v for k, v in assessment.criteria.items()},
        violations=[
            {
                "code": v.code,
                "title": v.kind.title,
                "criterion": str(v.kind.criterion),
                "severity": str(v.kind.severity),
                "detail": v.detail,
                "evidence": v.evidence,
                "example": v.kind.example,
            }
            for v in assessment.violations
        ],
        llm_pending=needs_llm,
    )
