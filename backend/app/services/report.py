"""Отчёт о практическом занятии.

Состав отчёта задан техническим заданием: действия обучающихся, замечания,
время заполнения карточки, отличие от норматива и грамматика. Инсайты по
типичным ошибкам группы считаются по каталогу нарушений, без обращения
к языковой модели — отчёт должен формироваться и в изолированном контуре.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field

from app.models.training import Attempt, TrainingSession
from app.services.violations import Severity, kind_of


@dataclass
class StudentResult:
    student_id: int
    student_name: str
    attempts: int = 0
    finished: int = 0
    scores: list[float] = field(default_factory=list)
    overdue: int = 0
    violations: collections.Counter = field(default_factory=collections.Counter)
    # Критические нарушения считаются отдельно от прочих: по ним занятие
    # не засчитывается независимо от среднего балла.
    critical: int = 0

    @property
    def average_score(self) -> float:
        return round(sum(self.scores) / len(self.scores), 3) if self.scores else 0.0

    def passed(self, pass_score: float, max_critical: int) -> bool | None:
        """Зачтена ли работа обучающегося по критериям успешности занятия.

        None, а не False, когда завершённых работ нет: обучающийся, до которого
        карточки не дошли, не «не сдал» — судить о нём не по чему, и в отчёте
        это должно отличаться от провала.
        """
        if not self.finished:
            return None
        return self.average_score >= pass_score and self.critical <= max_critical


@dataclass
class SessionReport:
    session: TrainingSession
    students: list[StudentResult]
    total_attempts: int
    finished_attempts: int
    average_score: float
    average_response_seconds: float | None
    overdue_share: float
    violations: collections.Counter
    grammar_issues: int
    insights: list[str]

    @property
    def pass_score(self) -> float:
        return self.session.pass_score

    @property
    def max_critical_violations(self) -> int:
        return self.session.max_critical_violations

    @property
    def passed_students(self) -> int:
        return sum(
            1
            for s in self.students
            if s.passed(self.pass_score, self.max_critical_violations)
        )

    @property
    def failed_students(self) -> int:
        return sum(
            1
            for s in self.students
            if s.passed(self.pass_score, self.max_critical_violations) is False
        )


def _insights(
    violations: collections.Counter, total: int, overdue_share: float, deadline: int
) -> list[str]:
    """Короткие выводы для преподавателя по типичным ошибкам группы."""
    if not total:
        return ["Занятие ещё не дало результатов: ни одна карточка не завершена."]

    notes: list[str] = []
    if overdue_share >= 0.3:
        notes.append(
            f"Норматив взятия в работу ({deadline} с) нарушен в "
            f"{overdue_share:.0%} карточек — стоит отработать скорость реакции."
        )
    for code, count in violations.most_common(3):
        # kind_of, а не каталог диспетчера: на занятии оператора 112 все коды
        # приходят из другого каталога, и отчёт молчал о них вовсе — при
        # восьми нарушениях сообщал, что системных ошибок не видно.
        kind = kind_of(code)
        share = count / total
        if share < 0.2:
            continue
        notes.append(f"«{kind.title}» — в {share:.0%} карточек. {kind.example}")

    critical = sum(
        c for code, c in violations.items()
        if kind_of(code).severity is Severity.CRITICAL
    )
    if critical and not notes:
        notes.append(f"Критических нарушений: {critical}. Разберите их индивидуально.")
    if not notes:
        notes.append("Группа работает в пределах регламента, системных ошибок не видно.")
    return notes


def build(session: TrainingSession, attempts: list[Attempt]) -> SessionReport:
    by_student: dict[int, StudentResult] = {}
    violations: collections.Counter = collections.Counter()
    response_times: list[float] = []
    overdue = 0
    finished = 0
    scores: list[float] = []
    grammar = 0
    deadline = session.pickup_deadline_seconds

    for attempt in attempts:
        result = by_student.setdefault(
            attempt.student_id,
            StudentResult(attempt.student_id, attempt.student.full_name),
        )
        result.attempts += 1

        primary = next(
            (e for e in attempt.events if e.status in ("Принята", "Не принята")), None
        )
        if primary is not None:
            response_times.append(primary.elapsed_seconds)
            if primary.elapsed_seconds > deadline:
                overdue += 1
                result.overdue += 1

        evaluation = attempt.evaluation
        if evaluation is None:
            continue

        finished += 1
        result.finished += 1
        scores.append(evaluation.score)
        result.scores.append(evaluation.score)
        grammar += len(evaluation.grammar_issues or [])
        for item in evaluation.violations or []:
            code = item.get("code")
            if code:
                violations[code] += 1
                result.violations[code] += 1
                if kind_of(code).severity is Severity.CRITICAL:
                    result.critical += 1

    return SessionReport(
        session=session,
        students=sorted(by_student.values(), key=lambda s: s.student_name),
        total_attempts=len(attempts),
        finished_attempts=finished,
        average_score=round(sum(scores) / len(scores), 3) if scores else 0.0,
        average_response_seconds=(
            round(sum(response_times) / len(response_times), 1) if response_times else None
        ),
        overdue_share=round(overdue / len(response_times), 3) if response_times else 0.0,
        violations=violations,
        grammar_issues=grammar,
        insights=_insights(
            violations,
            finished,
            overdue / len(response_times) if response_times else 0.0,
            deadline,
        ),
    )
