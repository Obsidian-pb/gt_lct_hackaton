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
from app.services.report import attempt_failed, critical_violations
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
    # Примечание преподавателя к этой работе, если оно оставлено. В личном
    # кабинете оно важнее автоматических замечаний: это адресный разбор.
    teacher_feedback: str | None = None
    teacher_feedback_by: str | None = None
    # Повторная выдача проваленной карточки и её итог: исправился ли.
    # В статистику повторы не входят — она считается по первому проходу.
    is_repeat: bool = False
    repeat_fixed: bool | None = None


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
    # Повторные выдачи: сколько завершено и в скольких обучающийся исправился.
    repeats_finished: int = 0
    repeats_fixed: int = 0


def _times(count: int) -> str:
    """«1 раз», «2 раза», «5 раз» — иначе рекомендация читается как машинная."""
    tail = count % 100
    if 11 <= tail <= 14:
        return f"{count} раз"
    return f"{count} раз" if count % 10 in (0, 1, 5, 6, 7, 8, 9) else f"{count} раза"


def _severity_rank(kind: ViolationKind) -> int:
    order = {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2}
    return order[kind.severity]


def _advice(
    mistakes: list[Mistake],
    finished: int,
    overdue: int,
    total_pickups: int,
    repeats: tuple[int, int] = (0, 0),
) -> list[str]:
    """Рекомендации по улучшению навыков — из собственных ошибок обучающегося.

    `repeats` — завершённые повторные выдачи и сколько из них исправлено.
    """
    if not finished:
        return [
            "Завершённых работ пока нет. Начните с любого назначенного вызова — "
            "после сдачи карточки появится разбор и первая статистика."
        ]

    notes: list[str] = []
    repeats_finished, repeats_fixed = repeats
    if repeats_finished:
        # Повтор — вторая попытка на той же карточке, и её итог говорит
        # о другом, чем средний балл: усвоен ли разбор.
        if repeats_fixed == repeats_finished:
            notes.append(
                f"Повторные выдачи: {repeats_finished}, все пройдены. Ошибки "
                "первого прохода исправлены — разбор пошёл впрок."
            )
        else:
            notes.append(
                f"Повторные выдачи: {repeats_finished}, исправлено "
                f"{repeats_fixed}. По оставшимся вернитесь к разбору первой "
                "попытки: ошибка повторилась на той же карточке."
            )
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
    repeats_finished = 0
    repeats_fixed = 0

    for attempt in attempts:
        mode = attempt.scenario.mode
        evaluation = attempt.evaluation

        # Повтор проваленной карточки в статистику не идёт: средний балл
        # и динамика считаются по первому проходу, как и зачёт в отчёте
        # преподавателя. В истории работ он остаётся — с итогом повтора.
        if attempt.repeat_of_id is not None:
            if evaluation is None:
                continue
            fixed = not attempt_failed(evaluation, attempt.session.pass_score)
            repeats_finished += 1
            repeats_fixed += int(fixed)
            works.append(
                Work(
                    attempt_id=attempt.id,
                    title=attempt.scenario.title,
                    mode=mode,
                    finished_at=as_utc(attempt.finished_at).isoformat(),
                    score=evaluation.score,
                    violations=len(evaluation.violations or []),
                    critical=critical_violations(evaluation.violations),
                    teacher_feedback=evaluation.teacher_feedback,
                    teacher_feedback_by=(
                        evaluation.teacher_feedback_by.full_name
                        if evaluation.teacher_feedback_by
                        else None
                    ),
                    is_repeat=True,
                    repeat_fixed=fixed,
                )
            )
            continue

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
                teacher_feedback=evaluation.teacher_feedback,
                teacher_feedback_by=(
                    evaluation.teacher_feedback_by.full_name
                    if evaluation.teacher_feedback_by
                    else None
                ),
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
        # Повторы сюда не входят: они идут в конце занятия и подтянули бы
        # вторую половину за счёт второй попытки на той же карточке.
        ordered = [
            w.score
            for w in sorted(works, key=lambda w: w.finished_at)
            if not w.is_repeat
        ]
        half = len(ordered) // 2
        first = sum(ordered[:half]) / half
        last = sum(ordered[half:]) / len(ordered[half:])
        trend = round(last - first, 3)

    return Progress(
        total=sum(1 for a in attempts if a.repeat_of_id is None),
        finished=finished,
        average_score=round(sum(scores) / finished, 3) if finished else 0.0,
        average_pickup_seconds=round(sum(pickups) / len(pickups), 1) if pickups else None,
        overdue_pickup=overdue,
        grammar_issues=grammar,
        trend=trend,
        by_mode=sorted(by_mode.values(), key=lambda s: str(s.mode)),
        mistakes=mistakes,
        works=works,
        advice=_advice(
            mistakes, finished, overdue, len(pickups), (repeats_finished, repeats_fixed)
        ),
        repeats_finished=repeats_finished,
        repeats_fixed=repeats_fixed,
    )
