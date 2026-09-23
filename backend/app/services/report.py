"""Отчёт о практическом занятии.

Состав отчёта задан техническим заданием: действия обучающихся, замечания,
время заполнения карточки, отличие от норматива и грамматика. Инсайты по
типичным ошибкам группы считаются по каталогу нарушений, без обращения
к языковой модели — отчёт должен формироваться и в изолированном контуре.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field

from app.models.training import Attempt, Evaluation, TrainingSession
from app.services.violations import Severity, kind_of


def critical_violations(violations: list[dict] | None) -> int:
    """Сколько критических нарушений в списке из оценки.

    Единственное место, где нарушение признаётся критическим для зачёта:
    тем же счётом пользуются отчёт, список работ и решение о повторе
    карточки — иначе они рано или поздно разошлись бы.
    """
    return sum(
        1
        for item in violations or []
        if item.get("code") and kind_of(item["code"]).severity is Severity.CRITICAL
    )


def attempt_failed(evaluation: Evaluation, pass_score: float) -> bool:
    """Провалена ли отдельная попытка.

    Балл ниже порога занятия или хотя бы одно критическое нарушение. Порог
    допустимых критических нарушений здесь не применяется: он задан на всё
    занятие, а одна карточка с критической ошибкой — это происшествие,
    на которое служба не выехала бы, и именно её стоит вернуть.
    """
    return evaluation.score < pass_score or critical_violations(evaluation.violations) > 0


@dataclass(frozen=True)
class RepeatResult:
    """Что вышло из повторной выдачи проваленной карточки."""

    attempt_id: int
    repeat_attempt_id: int
    scenario_title: str
    first_score: float | None
    # None — повтор ещё не завершён.
    repeat_score: float | None
    # Исправился ли обучающийся: повтор пройден по тем же критериям,
    # по которым провалилась первая попытка. None, пока повтора нет.
    fixed: bool | None


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
    # Повторные выдачи показываются отдельно и в средний балл не входят:
    # зачёт ставится за первый проход, а повтор отвечает на другой вопрос —
    # исправился ли обучающийся после разбора.
    repeats: list[RepeatResult] = field(default_factory=list)

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
    # Повторные выдачи по занятию в целом: сколько карточек вернулось,
    # сколько из них доведено до конца и в скольких обучающийся исправился.
    repeats_issued: int = 0
    repeats_finished: int = 0
    repeats_fixed: int = 0

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


def _repeats_note(issued: int, finished: int, fixed: int) -> str:
    """Фраза о повторных выдачах: что вернулось и чем кончилось."""
    if not finished:
        return (
            f"Проваленные карточки возвращены повторно: {issued}. "
            "Ни одна повторная выдача ещё не завершена."
        )
    return (
        f"Проваленные карточки возвращены повторно: {issued}. "
        f"Из {finished} завершённых повторов исправились в {fixed}."
    )


def _insights(
    violations: collections.Counter,
    total: int,
    overdue_share: float,
    deadline: int,
    repeats: tuple[int, int, int] = (0, 0, 0),
) -> list[str]:
    """Короткие выводы для преподавателя по типичным ошибкам группы.

    `repeats` — выдано, завершено и исправлено по повторным выдачам.
    """
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
    # Фраза о повторах — всегда последней: это не ошибка группы, а сведения
    # о том, чем закончился разбор ошибок по горячим следам.
    if repeats[0]:
        notes.append(_repeats_note(*repeats))
    return notes


def _repeat_results(
    session: TrainingSession, repeats: list[Attempt]
) -> dict[int, list[RepeatResult]]:
    """Итоги повторных выдач, сгруппированные по обучающемуся."""
    by_student: dict[int, list[RepeatResult]] = {}
    for repeat in repeats:
        original = repeat.repeat_of
        first = original.evaluation if original is not None else None
        second = repeat.evaluation
        by_student.setdefault(repeat.student_id, []).append(
            RepeatResult(
                attempt_id=repeat.repeat_of_id,
                repeat_attempt_id=repeat.id,
                scenario_title=repeat.scenario.title,
                first_score=first.score if first is not None else None,
                repeat_score=second.score if second is not None else None,
                fixed=(
                    not attempt_failed(second, session.pass_score)
                    if second is not None
                    else None
                ),
            )
        )
    return by_student


def build(session: TrainingSession, attempts: list[Attempt]) -> SessionReport:
    by_student: dict[int, StudentResult] = {}
    violations: collections.Counter = collections.Counter()
    response_times: list[float] = []
    overdue = 0
    finished = 0
    scores: list[float] = []
    grammar = 0
    deadline = session.pickup_deadline_seconds

    # Повторные выдачи отделяются до подсчёта: средний балл, зачёт
    # и типичные ошибки группы считаются по первому проходу, иначе одна
    # и та же ошибка, повторённая на возвращённой карточке, удваивалась бы.
    repeats = [a for a in attempts if a.repeat_of_id is not None]
    repeat_results = _repeat_results(session, repeats)

    for attempt in attempts:
        result = by_student.setdefault(
            attempt.student_id,
            StudentResult(attempt.student_id, attempt.student.full_name),
        )
        if attempt.repeat_of_id is not None:
            continue
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
        result.critical += critical_violations(evaluation.violations)

    for student_id, results in repeat_results.items():
        if student_id in by_student:
            by_student[student_id].repeats = results

    repeats_finished = sum(1 for r in repeats if r.evaluation is not None)
    repeats_fixed = sum(
        1 for results in repeat_results.values() for r in results if r.fixed
    )

    return SessionReport(
        session=session,
        students=sorted(by_student.values(), key=lambda s: s.student_name),
        total_attempts=len(attempts) - len(repeats),
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
            (len(repeats), repeats_finished, repeats_fixed),
        ),
        repeats_issued=len(repeats),
        repeats_finished=repeats_finished,
        repeats_fixed=repeats_fixed,
    )
