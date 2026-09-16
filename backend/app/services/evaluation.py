"""Детерминированная оценка действий диспетчера ДДС.

Считается без обращения к LLM: тайминг, корректность и последовательность
статусов, наличие обязательных комментариев. Смысловую полноту комментариев
дооценивает LLM отдельно и асинхронно — см. app/llm.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.response_status import (
    COMMENT_REQUIRED,
    PRIMARY,
    ResponseStatus,
    check_transition,
)
from app.services.violations import CATALOG, Criterion, Severity, Violation

SEVERITY_PENALTY = {Severity.CRITICAL: 1.0, Severity.MAJOR: 0.5, Severity.MINOR: 0.25}


@dataclass(frozen=True)
class StatusEvent:
    status: ResponseStatus
    elapsed_seconds: float
    comment: str | None = None


@dataclass(frozen=True)
class Expectation:
    """Эталон занятия: что диспетчер обязан был сделать с этой карточкой."""

    primary_status: ResponseStatus
    # Профильное ли происшествие для службы обучающегося. Отказ от профильного
    # происшествия — грубое нарушение даже при корректном оформлении.
    is_profile: bool
    # Два норматива измеряют разное: первый — скорость реакции на поступивший
    # вызов, второй — время работы по существу. Разделение задано
    # организаторами и позволяет отличить нерасторопность от медленной работы.
    pickup_deadline_seconds: int = 30
    handling_deadline_seconds: int = 180
    # Факты, которые обязаны прозвучать в комментарии (проверяет LLM).
    required_comment_points: tuple[str, ...] = ()
    # Ожидается ли ведение статусов хода работ (длительное реагирование).
    expects_progress_statuses: bool = False


@dataclass
class Assessment:
    violations: list[Violation] = field(default_factory=list)
    primary_status: ResponseStatus | None = None
    primary_elapsed_seconds: float | None = None
    # Сколько секунд прошло до взятия карточки в работу и сколько заняла
    # сама обработка. None, если соответствующее событие не наступило.
    pickup_seconds: float | None = None
    handling_seconds: float | None = None

    @property
    def score(self) -> float:
        penalty = sum(SEVERITY_PENALTY[v.kind.severity] for v in self.violations)
        return max(0.0, 1.0 - penalty / 3.0)

    @property
    def criteria(self) -> dict[Criterion, bool]:
        failed = {v.kind.criterion for v in self.violations}
        return {c: c not in failed for c in Criterion}


def evaluate(
    events: list[StatusEvent],
    expected: Expectation,
    pickup_seconds: float | None = None,
    handling_seconds: float | None = None,
) -> Assessment:
    result = Assessment(pickup_seconds=pickup_seconds, handling_seconds=handling_seconds)
    ordered = sorted(events, key=lambda e: e.elapsed_seconds)

    _check_sequence(ordered, result)
    _check_timings(expected, result)
    primary = next((e for e in ordered if e.status in PRIMARY), None)

    if primary is None:
        result.violations.append(
            Violation("V1", "Первичный статус реагирования не проставлен")
        )
        return result

    result.primary_status = primary.status
    result.primary_elapsed_seconds = primary.elapsed_seconds
    _check_primary_correctness(primary, expected, result)
    _check_comments(ordered, result)
    _check_progress(ordered, expected, result)
    return result


def _check_timings(expected: Expectation, result: Assessment) -> None:
    """Проверяет оба норматива: скорость взятия в работу и время обработки."""
    if result.pickup_seconds is not None and (
        result.pickup_seconds > expected.pickup_deadline_seconds
    ):
        overdue = result.pickup_seconds - expected.pickup_deadline_seconds
        result.violations.append(
            Violation(
                "V8",
                f"Карточка взята в работу через {result.pickup_seconds:.0f} с "
                f"при нормативе {expected.pickup_deadline_seconds} с "
                f"(опоздание {overdue:.0f} с)",
                evidence=f"{result.pickup_seconds:.1f} с",
            )
        )

    if result.handling_seconds is not None and (
        result.handling_seconds > expected.handling_deadline_seconds
    ):
        overdue = result.handling_seconds - expected.handling_deadline_seconds
        result.violations.append(
            Violation(
                "V9",
                f"Обработка заняла {result.handling_seconds:.0f} с "
                f"при нормативе {expected.handling_deadline_seconds} с "
                f"(превышение {overdue:.0f} с)",
                evidence=f"{result.handling_seconds:.1f} с",
            )
        )


def _check_sequence(events: list[StatusEvent], result: Assessment) -> None:
    current: ResponseStatus | None = None
    for event in events:
        check = check_transition(current, event.status, require_comment=False)
        if not check.allowed:
            result.violations.append(
                Violation("V7", check.reason or "Недопустимый переход", evidence=str(event.status))
            )
            continue
        current = event.status


def _check_primary_correctness(
    primary: StatusEvent, expected: Expectation, result: Assessment
) -> None:
    if primary.status == expected.primary_status:
        return
    if expected.is_profile and primary.status is ResponseStatus.REJECTED:
        result.violations.append(
            Violation(
                "V3",
                "Отказ от реагирования на профильное для службы происшествие",
                evidence=str(primary.status),
            )
        )
        return
    result.violations.append(
        Violation(
            "V2",
            f"Проставлен статус «{primary.status}», следовало «{expected.primary_status}»",
            evidence=str(primary.status),
        )
    )


def _check_comments(events: list[StatusEvent], result: Assessment) -> None:
    for event in events:
        if event.status in COMMENT_REQUIRED and not (event.comment or "").strip():
            result.violations.append(
                Violation(
                    "V4",
                    f"Статус «{event.status}» проставлен без обязательного комментария",
                    evidence=str(event.status),
                )
            )


def _check_progress(
    events: list[StatusEvent], expected: Expectation, result: Assessment
) -> None:
    if not expected.expects_progress_statuses:
        return
    if any(e.status is ResponseStatus.ACCEPTED for e in events) and not any(
        e.status is ResponseStatus.RESPONSE_STARTED for e in events
    ):
        result.violations.append(
            Violation("V6", "Реагирование принято, но статусы хода работ не вносились")
        )


def add_llm_violations(result: Assessment, incomplete_points: list[str]) -> Assessment:
    """Дописывает в оценку результат смысловой проверки комментариев."""
    for point in incomplete_points:
        result.violations.append(Violation("V5", f"В комментарии не отражено: {point}"))
    return result


__all__ = [
    "Assessment",
    "CATALOG",
    "Expectation",
    "StatusEvent",
    "add_llm_violations",
    "evaluate",
]
