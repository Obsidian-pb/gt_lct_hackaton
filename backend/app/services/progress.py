"""Личный прогресс обучающегося.

Техническое задание требует, чтобы обучающийся видел собственные результаты,
статистику выполнения заданий, историю ошибок и рекомендации по улучшению
навыков. До сих пор всё это было доступно только преподавателю в отчёте
по занятию, а обучающийся видел лишь разбор отдельной карточки.

Считается по тем же данным, что и отчёт преподавателя, но в разрезе одного
человека и по всем его занятиям сразу. Рекомендации выводятся из каталога
нарушений, без обращения к языковой модели: личный кабинет обязан работать
и в изолированном контуре, и при недоступной модели.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field

from app.models.base import as_utc
from app.models.training import Attempt, TrainingMode
from app.services.violations import Severity, ViolationKind, kind_of

# Меньшее число завершённых работ не позволяет говорить о динамике:
# два-три результата различаются случайно, а не по уровню подготовки.
MIN_WORKS_FOR_TREND = 6


@dataclass
class ModeStats:
    """Статистика по одному режиму обучения."""

    mode: TrainingMode
    attempts: int = 0
    finished: int = 0
    scores: list[float] = field(default_factory=list)
    overdue_pickup: int = 0

    @property
    def average_score(self) -> float:
        return round(sum(self.scores) / len(self.scores), 3) if self.scores else 0.0


@dataclass(frozen=True)
class Work:
    """Одна завершённая работа в истории обучающегося."""

    attempt_id: int
    title: str
    mode: TrainingMode
    finished_at: str
    score: float
    violations: int
    critical: int


@dataclass(frozen=True)
class Mistake:
    """Повторяющаяся ошибка обучающегося."""

    code: str
    title: str
    severity: str
    criterion: str
    count: int
    share: float
    example: str


@dataclass
class Progress:
    total: int
    finished: int
    average_score: float
    average_pickup_seconds: float | None
    overdue_pickup: int
    grammar_issues: int
    # Насколько средний балл последней половины работ отличается от первой.
    # None, если работ слишком мало, чтобы говорить о динамике.
    trend: float | None
    by_mode: list[ModeStats]
    mistakes: list[Mistake]
    works: list[Work]
    advice: list[str]


def _times(count: int) -> str:
    """«1 раз», «2 раза», «5 раз» — иначе рекомендация читается как машинная."""
    tail = count % 100
    if 11 <= tail <= 14:
        return f"{count} раз"
    return f"{count} раз" if count % 10 in (0, 1, 5, 6, 7, 8, 9) else f"{count} раза"


def _severity_rank(kind: ViolationKind) -> int:
    order = {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2}
    return order[kind.severity]


def _advice(mistakes: list[Mistake], finished: int, overdue: int, total_pickups: int) -> list[str]:
    """Рекомендации по улучшению навыков — из собственных ошибок обучающегося."""
    if not finished:
        return [
            "Завершённых работ пока нет. Начните с любого назначенного вызова — "
            "после сдачи карточки появится разбор и первая статистика."
        ]

    notes: list[str] = []
    if total_pickups and overdue / total_pickups >= 0.25:
        notes.append(
            f"Норматив взятия карточки в работу нарушен в {overdue} случаях "
            f"из {total_pickups}. Берите карточку в работу сразу, а разбирайтесь "
            "с содержанием уже внутри: норматив считается до первого статуса."
        )

    # Разбираем сначала критические ошибки: они означают, что служба
    # не выехала бы на происшествие или карточка ушла в отдел контроля.
    for mistake in mistakes[:3]:
        notes.append(f"«{mistake.title}» — {_times(mistake.count)}. {mistake.example}")

    if not notes:
        notes.append(
            "Системных ошибок не видно: работы выполняются в пределах регламента. "
            "Попросите преподавателя добавить сценарии посложнее."
        )
    return notes


def build(attempts: list[Attempt]) -> Progress:
    """Собирает личный прогресс по всем работам одного обучающегося."""
    by_mode: dict[TrainingMode, ModeStats] = {}
    counts: collections.Counter = collections.Counter()
    scores: list[float] = []
    pickups: list[float] = []
    overdue = 0
    grammar = 0
    works: list[Work] = []

    for attempt in attempts:
        mode = attempt.scenario.mode
        stats = by_mode.setdefault(mode, ModeStats(mode=mode))
        stats.attempts += 1

        # Момент взятия в работу: для диспетчера — первый статус реагирования,
        # для оператора 112 — открытие карточки вызова.
        pickup: float | None = None
        if mode is TrainingMode.DISPATCHER:
            primary = next(
                (e for e in attempt.events if e.status in ("Принята", "Не принята")), None
            )
            pickup = primary.elapsed_seconds if primary else None
        elif attempt.opened_at is not None:
            pickup = (as_utc(attempt.opened_at) - as_utc(attempt.issued_at)).total_seconds()

        deadline = attempt.session.pickup_deadline_seconds
        if pickup is not None:
            pickups.append(pickup)
            if pickup > deadline:
                overdue += 1
                stats.overdue_pickup += 1

        evaluation = attempt.evaluation
        if evaluation is None:
            continue

        stats.finished += 1
        stats.scores.append(evaluation.score)
        scores.append(evaluation.score)
        grammar += len(evaluation.grammar_issues or [])

        critical = 0
        for item in evaluation.violations or []:
            code = item.get("code")
            if not code:
                continue
            counts[code] += 1
            if kind_of(code).severity is Severity.CRITICAL:
                critical += 1

        works.append(
            Work(
                attempt_id=attempt.id,
                title=attempt.scenario.title,
                mode=mode,
                finished_at=as_utc(attempt.finished_at).isoformat(),
                score=evaluation.score,
                violations=len(evaluation.violations or []),
                critical=critical,
            )
        )

    finished = len(scores)
    mistakes = sorted(
        (
            Mistake(
                code=code,
                title=kind_of(code).title,
                severity=str(kind_of(code).severity),
                criterion=str(kind_of(code).criterion),
                count=count,
                share=round(count / finished, 3) if finished else 0.0,
                example=kind_of(code).example,
            )
            for code, count in counts.items()
        ),
        # Сначала тяжёлые, при равной тяжести — частые.
        key=lambda m: (_severity_rank(kind_of(m.code)), -m.count),
    )

    works.sort(key=lambda w: w.finished_at, reverse=True)

    trend = None
    if finished >= MIN_WORKS_FOR_TREND:
        # Работы в хронологическом порядке: сравниваем первую половину
        # со второй, чтобы увидеть направление, а не отдельный провал.
        ordered = [w.score for w in sorted(works, key=lambda w: w.finished_at)]
        half = len(ordered) // 2
        first = sum(ordered[:half]) / half
        last = sum(ordered[half:]) / len(ordered[half:])
        trend = round(last - first, 3)

    return Progress(
        total=len(attempts),
        finished=finished,
        average_score=round(sum(scores) / finished, 3) if finished else 0.0,
        average_pickup_seconds=round(sum(pickups) / len(pickups), 1) if pickups else None,
        overdue_pickup=overdue,
        grammar_issues=grammar,
        trend=trend,
        by_mode=sorted(by_mode.values(), key=lambda s: str(s.mode)),
        mistakes=mistakes,
        works=works,
        advice=_advice(mistakes, finished, overdue, len(pickups)),
    )
