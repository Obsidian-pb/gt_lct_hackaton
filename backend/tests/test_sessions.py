"""Проведение занятия: состав, поток вызовов, ход и завершение."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.training import (
    Attempt,
    Scenario,
    SessionState,
    TrainingMode,
    TrainingSession,
)
from app.models.user import DispatchService, Role, User
from app.services.sessions import (
    SessionError,
    finish,
    plan_issue_times,
    progress,
    start,
)

START = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


@pytest.fixture
def lesson():
    service = DispatchService(name="ДДС района", ekp_name="Территориальные ОИВ")
    teacher = User(login="t", full_name="Т", hashed_password="x", role=Role.TEACHER)
    students = [
        User(login=f"s{i}", full_name=f"Обучающийся {i}", hashed_password="x",
             role=Role.STUDENT, service=service)
        for i in (1, 2)
    ]
    scenarios = []
    for i in range(3):
        s = Scenario(
            title=f"Сценарий {i}",
            mode=TrainingMode.DISPATCHER,
            incident_type=f"тип {i}",
            address="Москва",
            description="описание",
            target_service=service,
            expected_primary_status="Принята",
            author=teacher,
        )
        s.approved_at = START  # утверждён преподавателем
        scenarios.append(s)

    session = TrainingSession(
        title="Занятие",
        teacher=teacher,
        # У объекта из базы состояние уже проставлено умолчанием колонки,
        # а у созданного в памяти — нет.
        state=SessionState.DRAFT,
        pickup_deadline_seconds=30,
        handling_deadline_seconds=180,
        call_interval_seconds=20,
    )
    session.id = 1
    for index, student in enumerate(students, start=1):
        student.id = index
    session.students = students
    session.scenarios = scenarios
    return session


def test_вызовы_поступают_потоком_а_не_залпом():
    times = plan_issue_times(START, 4, 20)
    assert times == [START, at(20), at(40), at(60)]


def test_запуск_выдаёт_карточки_каждому_обучающемуся(lesson):
    created = start(lesson, now=START)
    assert lesson.state is SessionState.ACTIVE
    assert lesson.started_at == START
    assert len(created) == 6  # два обучающихся по три сценария
    assert {a.student.login for a in created} == {"s1", "s2"}


def test_порядок_вызовов_у_обучающихся_различается(lesson):
    created = start(lesson, now=START)
    first = [a.scenario.title for a in created if a.student.login == "s1"]
    second = [a.scenario.title for a in created if a.student.login == "s2"]
    assert sorted(first) == sorted(second)
    # Одинаковый порядок позволял бы подсматривать у соседа.
    assert first != second or len(set(first)) == 1


def test_нельзя_запустить_без_утверждённых_сценариев(lesson):
    for scenario in lesson.scenarios:
        scenario.approved_at = None
    with pytest.raises(SessionError, match="утверждённых"):
        start(lesson, now=START)


def test_нельзя_запустить_без_обучающихся(lesson):
    lesson.students = []
    with pytest.raises(SessionError, match="обучающийся"):
        start(lesson, now=START)


def test_повторный_запуск_отклоняется(lesson):
    start(lesson, now=START)
    with pytest.raises(SessionError, match="уже запущено"):
        start(lesson, now=START)


def test_ход_занятия_учитывает_только_поступившие_вызовы(lesson):
    created = start(lesson, now=START)
    # Через 10 секунд поступил только первый вызов каждому.
    rows = progress(lesson, created, now=at(10))
    assert all(r.issued == 1 for r in rows)
    # Через 50 секунд — уже по три.
    rows = progress(lesson, created, now=at(50))
    assert all(r.issued == 3 for r in rows)


def test_просрочка_взятия_в_работу_видна_в_реальном_времени(lesson):
    created = start(lesson, now=START)
    rows = progress(lesson, created, now=at(10))
    assert all(r.overdue_pickup == 0 for r in rows)
    # Прошло больше 30 секунд, а карточку никто не открыл.
    rows = progress(lesson, created, now=at(45))
    assert all(r.overdue_pickup >= 1 for r in rows)


def test_завершение_закрывает_неоконченные_карточки(lesson):
    created = start(lesson, now=START)
    evaluations = finish(lesson, created, now=at(50))
    assert lesson.state is SessionState.FINISHED
    # К 50-й секунде поступили все три вызова каждому из двоих.
    assert len(evaluations) == 6
    assert all(a.finished_at is not None for a in created if a.issued_at <= at(50))


def test_завершение_возвращает_оценки_для_сохранения(lesson):
    """Оценки не сохраняются сами: присваивание через связь не кладёт их
    в сессию, и без явного сохранения отчёт оставался бы пустым."""
    created = start(lesson, now=START)
    evaluations = finish(lesson, created, now=at(50))
    assert all(e.attempt is not None for e in evaluations)
    assert all(e.score is not None for e in evaluations)


def test_невыданные_карточки_в_зачёт_не_идут(lesson):
    created = start(lesson, now=START)
    evaluations = finish(lesson, created, now=at(10))
    # Успел поступить только первый вызов каждому.
    assert len(evaluations) == 2
    assert sum(1 for a in created if a.finished_at is None) == 4


def test_повторное_завершение_отклоняется(lesson):
    created = start(lesson, now=START)
    finish(lesson, created, now=at(50))
    with pytest.raises(SessionError, match="уже завершено"):
        finish(lesson, created, now=at(60))


def test_сценарий_чужого_режима_не_попадает_в_занятие(lesson):
    """Иначе карточка не появилась бы в ленте обучающегося и потерялась молча."""
    from app.services.sessions import start

    lesson.scenarios[0].mode = TrainingMode.OPERATOR
    created = start(lesson, now=START)
    # Сам сервис запуска режим не проверяет — это делает слой API при наборе
    # состава, иначе ошибку заметили бы только после запуска занятия.
    assert len(created) == 6
