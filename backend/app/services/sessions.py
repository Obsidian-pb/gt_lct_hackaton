"""Проведение практического занятия.

Занятие связывает обе половины продукта: преподаватель собирает состав
и утверждённые сценарии, запускает — и карточки попадают в ленты
обучающихся. До появления этого звена утверждённый сценарий физически
не мог дойти до обучающегося.

Вызовы поступают потоком, а не залпом: каждой карточке при запуске
назначается свой момент поступления. Обучающийся ведёт несколько карточек
одновременно и вынужден расставлять приоритеты — это отрабатываемый навык,
а не побочный эффект.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models.base import as_utc, utcnow
from app.models.training import Attempt, Evaluation, SessionState, TrainingSession
from app.services import attempts as attempt_service
from app.services import report as report_service


class SessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class StudentProgress:
    student_id: int
    student_name: str
    issued: int
    opened: int
    finished: int
    # Карточки, по которым уже просрочено взятие в работу.
    overdue_pickup: int
    # Сколько карточек висит на обучающемся прямо сейчас.
    in_work: int
    # Сколько из поступивших карточек — повторные выдачи проваленных.
    repeats: int = 0


def plan_issue_times(
    started_at: datetime, count: int, interval_seconds: int
) -> list[datetime]:
    """Моменты поступления вызовов.

    Первый вызов приходит сразу, остальные — через заданный интервал.
    Благодаря заранее рассчитанному расписанию фоновый планировщик не нужен:
    лента просто не показывает карточки, чьё время ещё не настало.
    """
    return [started_at + timedelta(seconds=i * interval_seconds) for i in range(count)]


def start(session: TrainingSession, now: datetime | None = None) -> list[Attempt]:
    if session.state is not SessionState.DRAFT:
        raise SessionError("Занятие уже запущено или завершено")
    if not session.students:
        raise SessionError("В занятие не включён ни один обучающийся")

    approved = [s for s in session.scenarios if s.is_approved]
    if not approved:
        raise SessionError(
            "Нет утверждённых сценариев: обучающимся выдаются только "
            "проверенные преподавателем карточки"
        )

    moment = now or utcnow()
    session.state = SessionState.ACTIVE
    session.started_at = moment

    created: list[Attempt] = []
    for student in session.students:
        # Порядок вызовов у каждого свой: иначе обучающиеся видят одно и то же
        # в одной и той же последовательности и подсказывают друг другу.
        order = list(approved)
        random.Random(f"{session.id}-{student.id}").shuffle(order)
        # Раздача по уровням сложности: карточки поступают от простых
        # к сложным. Сортировка устойчива, поэтому внутри одного уровня
        # сохраняется перемешанный порядок и подсказать соседу по-прежнему
        # нечего. Адаптивности по ходу занятия ТЗ не требует, а уровень
        # задания преподаватель выбирает сам при подборе состава.
        # «or 0» — у сценария, ещё не сохранённого в базу, уровень не проставлен:
        # умолчание колонки срабатывает только при записи.
        order.sort(key=lambda scenario: scenario.difficulty or 0)
        times = plan_issue_times(moment, len(order), session.call_interval_seconds)
        for scenario, issued_at in zip(order, times):
            attempt = Attempt(
                session=session,
                student=student,
                scenario=scenario,
                issued_at=issued_at,
            )
            created.append(attempt)
    return created


def _is_repeat_of(candidate: Attempt, attempt: Attempt) -> bool:
    # Сравнение по связи, а не только по ключу: у попытки, созданной
    # в этом же вызове и ещё не записанной, номера нет.
    if candidate.repeat_of is attempt:
        return True
    return attempt.id is not None and candidate.repeat_of_id == attempt.id


def schedule_repeat(
    attempt: Attempt,
    evaluation: Evaluation,
    planned: list[Attempt],
    now: datetime | None = None,
) -> Attempt | None:
    """Возвращает проваленную карточку обучающемуся в том же занятии.

    Вызывается сразу после детерминированной части оценки, не дожидаясь
    языковой модели: ошибка разбирается по горячим следам, а разбор
    комментария балл ниже порога не поднимет.

    `planned` — все выдачи этого обучающегося в этом занятии, включая уже
    назначенные повторы: новая карточка встаёт после последней из них,
    чтобы повтор не вклинивался в поток, а завершал его. Раньше «сейчас»
    выдача не назначается — иначе она пришла бы задним числом и норматив
    взятия в работу оказался бы нарушен ещё до появления карточки в ленте.

    Возвращает созданную попытку или None, если повтор не положен: флаг
    у занятия выключен, занятие завершено, попытка сама была повтором,
    повтор на неё уже назначен или работа зачтена. Сохранить попытку
    должен вызывающий.
    """
    session = attempt.session
    if not session.repeat_failed or session.state is SessionState.FINISHED:
        return None
    # Повтор повтора не выдаётся: второй провал разбирает преподаватель.
    if attempt.repeat_of_id is not None or attempt.repeat_of is not None:
        return None
    if any(_is_repeat_of(p, attempt) for p in planned):
        return None
    if not report_service.attempt_failed(evaluation, session.pass_score):
        return None

    moment = now or utcnow()
    last_issue = max((as_utc(p.issued_at) for p in planned), default=moment)
    issued_at = max(
        moment, last_issue + timedelta(seconds=session.call_interval_seconds)
    )
    return Attempt(
        session=session,
        student=attempt.student,
        scenario=attempt.scenario,
        repeat_of=attempt,
        issued_at=issued_at,
    )


def finish(
    session: TrainingSession, attempts: list[Attempt], now: datetime | None = None
) -> list[Evaluation]:
    """Завершает занятие и закрывает незаконченные карточки.

    Незавершённая карточка — тоже результат: она означает, что обучающийся
    до неё не добрался, и в отчёте это должно быть видно. Карточки, чьё
    время ещё не пришло, — в том числе назначенные повторы, — не трогаются
    и в зачёт не идут.

    Возвращает созданные оценки: их должен сохранить вызывающий. Присваивание
    attempt.evaluation не добавляет объект в сессию — в SQLAlchemy 2.0 каскад
    save-update через backref убран, и оценки молча терялись бы.
    """
    if session.state is SessionState.FINISHED:
        raise SessionError("Занятие уже завершено")

    moment = now or utcnow()
    session.state = SessionState.FINISHED
    session.finished_at = moment

    created: list[Evaluation] = []
    for attempt in attempts:
        # Карточки, время которых ещё не пришло, в зачёт не идут.
        if as_utc(attempt.issued_at) > moment:
            continue
        if attempt.finished_at is None:
            attempt_service.finish(attempt, now=moment)
        if attempt.evaluation is None:
            created.append(attempt_service.build_evaluation(attempt))
    return created


def progress(session: TrainingSession, attempts: list[Attempt], now: datetime | None = None) -> list[StudentProgress]:
    """Ход занятия в реальном времени — то, что преподаватель видит во время."""
    moment = now or utcnow()
    by_student: dict[int, dict] = {}

    for attempt in attempts:
        if as_utc(attempt.issued_at) > moment:
            continue  # вызов ещё не поступил
        # Группируем по связи, а не по внешнему ключу: у ещё не сохранённой
        # попытки student_id пуст, и все строки схлопнулись бы в одну.
        row = by_student.setdefault(
            attempt.student.id,
            {
                "name": attempt.student.full_name,
                "issued": 0,
                "opened": 0,
                "finished": 0,
                "overdue_pickup": 0,
                "in_work": 0,
                "repeats": 0,
            },
        )
        row["issued"] += 1
        if attempt.repeat_of_id is not None or attempt.repeat_of is not None:
            row["repeats"] += 1
        if attempt.opened_at is not None:
            row["opened"] += 1
        if attempt.finished_at is not None:
            row["finished"] += 1
        else:
            row["in_work"] += 1

        pickup_limit = session.pickup_deadline_seconds
        if attempt.opened_at is None:
            waiting = (moment - as_utc(attempt.issued_at)).total_seconds()
            if waiting > pickup_limit:
                row["overdue_pickup"] += 1
        else:
            taken = (as_utc(attempt.opened_at) - as_utc(attempt.issued_at)).total_seconds()
            if taken > pickup_limit:
                row["overdue_pickup"] += 1

    return [
        StudentProgress(
            student_id=student_id,
            student_name=row["name"],
            issued=row["issued"],
            opened=row["opened"],
            finished=row["finished"],
            overdue_pickup=row["overdue_pickup"],
            in_work=row["in_work"],
            repeats=row["repeats"],
        )
        for student_id, row in sorted(by_student.items(), key=lambda kv: kv[1]["name"])
    ]
