"""Возврат проваленной карточки в том же занятии.

Повтор назначается сразу после детерминированной оценки, встаёт в конец
потока обучающегося и в средний балл первого прохода не входит: отчёт
показывает его отдельно — исправился обучающийся или нет.
"""

import collections
import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.training import (
    Attempt,
    CallOutcome,
    Evaluation,
    Scenario,
    SessionState,
    TrainingMode,
    TrainingSession,
)
from app.models.user import DispatchService, Role, User
from app.services import report
from app.services.sessions import finish, progress, schedule_repeat, start
from app.services.response_status import ResponseStatus as S
from tests.test_api import token

START = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def violation(code: str) -> dict:
    return {"code": code, "title": "", "severity": "", "detail": "", "example": ""}


def graded(attempt: Attempt, score: float, codes: list[str] = ()) -> Evaluation:
    """Детерминированная оценка попытки — то, после чего решается повтор."""
    return Evaluation(
        attempt=attempt,
        score=score,
        criteria={},
        violations=[violation(c) for c in codes],
        llm_pending=False,
    )


# --- Сервис: когда повтор назначается и на какое время ----------------------


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
        s.approved_at = START
        scenarios.append(s)

    session = TrainingSession(
        title="Занятие с повтором",
        teacher=teacher,
        state=SessionState.DRAFT,
        pickup_deadline_seconds=30,
        handling_deadline_seconds=180,
        call_interval_seconds=20,
        # У объекта в памяти умолчания колонок не срабатывают.
        pass_score=0.7,
        max_critical_violations=0,
        repeat_failed=True,
    )
    session.id = 1
    for index, student in enumerate(students, start=1):
        student.id = index
    session.students = students
    session.scenarios = scenarios
    return session


@pytest.fixture
def flow(lesson):
    """Запущенное занятие и выдачи первого обучающегося: 0, 20 и 40 секунд."""
    created = start(lesson, now=START)
    mine = sorted(
        (a for a in created if a.student.login == "s1"), key=lambda a: a.issued_at
    )
    return lesson, mine


def test_провал_по_баллу_возвращает_карточку(flow):
    lesson, mine = flow
    first = mine[0]
    repeat = schedule_repeat(first, graded(first, 0.4), mine, now=at(15))

    assert repeat is not None
    assert repeat.repeat_of is first
    assert repeat.scenario is first.scenario
    assert repeat.student is first.student
    assert repeat.session is lesson
    # После последней запланированной выдачи (40 с) через интервал вызовов.
    assert repeat.issued_at == at(60)


def test_провал_по_критическому_нарушению_возвращает_карточку(flow):
    """Балл выше порога, но служба не выехала бы — карточка возвращается."""
    _, mine = flow
    first = mine[0]
    repeat = schedule_repeat(first, graded(first, 0.9, ["V1"]), mine, now=at(15))
    assert repeat is not None


def test_зачтённая_карточка_не_возвращается(flow):
    _, mine = flow
    first = mine[0]
    assert schedule_repeat(first, graded(first, 0.9), mine, now=at(15)) is None


def test_при_выключенном_повторе_карточка_не_возвращается(flow):
    lesson, mine = flow
    lesson.repeat_failed = False
    first = mine[0]
    assert schedule_repeat(first, graded(first, 0.1), mine, now=at(15)) is None


def test_в_завершённом_занятии_повтор_не_назначается(flow):
    lesson, mine = flow
    lesson.state = SessionState.FINISHED
    first = mine[0]
    assert schedule_repeat(first, graded(first, 0.1), mine, now=at(15)) is None


def test_повтор_повтора_не_выдаётся(flow):
    """Второй провал той же карточки разбирает преподаватель, а не автомат."""
    _, mine = flow
    first = mine[0]
    repeat = schedule_repeat(first, graded(first, 0.4), mine, now=at(15))
    planned = mine + [repeat]
    assert schedule_repeat(repeat, graded(repeat, 0.2), planned, now=at(70)) is None


def test_на_одну_попытку_не_больше_одного_повтора(flow):
    _, mine = flow
    first = mine[0]
    evaluation = graded(first, 0.4)
    repeat = schedule_repeat(first, evaluation, mine, now=at(15))
    assert schedule_repeat(first, evaluation, mine + [repeat], now=at(16)) is None


def test_повтор_встаёт_после_уже_назначенных_повторов(flow):
    """Поток не прерывается: каждый следующий повтор — в конец очереди."""
    _, mine = flow
    first, second = mine[0], mine[1]
    repeat_one = schedule_repeat(first, graded(first, 0.4), mine, now=at(15))
    repeat_two = schedule_repeat(
        second, graded(second, 0.4), mine + [repeat_one], now=at(35)
    )
    assert repeat_one.issued_at == at(60)
    assert repeat_two.issued_at == at(80)


def test_повтор_не_назначается_задним_числом(flow):
    """Все выдачи давно позади — повтор приходит сейчас, а не в прошлом."""
    _, mine = flow
    last = mine[-1]
    repeat = schedule_repeat(last, graded(last, 0.4), mine, now=at(500))
    assert repeat.issued_at == at(500)


def test_завершение_занятия_не_трогает_невыданный_повтор(flow):
    lesson, mine = flow
    first = mine[0]
    repeat = schedule_repeat(first, graded(first, 0.4), mine, now=at(15))
    # Повтор создан со ссылкой на занятие и уже стоит в его выдачах.
    everything = list(lesson.attempts)
    assert repeat in everything

    evaluations = finish(lesson, everything, now=at(50))

    # Шесть карточек первого прохода: у первой оценка уже была, остальные
    # закрыты при завершении. Повтор на 60-й секунде не выдан и не оценён.
    assert len(evaluations) == 5
    assert repeat.finished_at is None
    assert repeat.evaluation is None


def test_ход_занятия_показывает_повтор_когда_он_поступил(flow):
    lesson, mine = flow
    first = mine[0]
    schedule_repeat(first, graded(first, 0.4), mine, now=at(15))
    everything = list(lesson.attempts)

    before = {r.student_name: r for r in progress(lesson, everything, now=at(50))}
    assert before["Обучающийся 1"].issued == 3
    assert before["Обучающийся 1"].repeats == 0

    after = {r.student_name: r for r in progress(lesson, everything, now=at(70))}
    assert after["Обучающийся 1"].issued == 4
    assert after["Обучающийся 1"].repeats == 1
    assert after["Обучающийся 2"].repeats == 0


# --- Отчёт и выгрузка --------------------------------------------------------


def enable_repeat(db_factory, interval: int = 0) -> None:
    """Включает повтор у занятия из общих фикстур.

    Интервал ноль — чтобы повтор появился в ленте сразу: иначе в тесте
    пришлось бы ждать настоящие секунды.
    """
    with db_factory() as db:
        session = db.scalar(select(TrainingSession))
        session.repeat_failed = True
        session.call_interval_seconds = interval
        db.commit()


@pytest.fixture
def repeated(db_factory):
    """Занятие, где Иванов провалил одну из двух карточек и исправился на повторе."""
    with db_factory() as db:
        session = db.scalar(select(TrainingSession))
        session.repeat_failed = True
        student = db.scalar(select(User).where(User.login == "student"))
        scenario = db.scalar(select(Scenario))
        moment = datetime.now(timezone.utc) - timedelta(minutes=10)

        def attempt(score: float, codes: list[str], offset: int, repeat_of=None):
            row = Attempt(
                session=session,
                student=student,
                scenario=scenario,
                repeat_of=repeat_of,
                issued_at=moment + timedelta(minutes=offset),
                finished_at=moment + timedelta(minutes=offset, seconds=50),
            )
            row.evaluation = Evaluation(
                score=score,
                criteria={},
                violations=[violation(c) for c in codes],
                llm_pending=False,
            )
            db.add(row)
            return row

        failed = attempt(0.5, ["V1"], 1)
        attempt(0.9, [], 2)
        attempt(0.95, [], 3, repeat_of=failed)
        db.commit()
    return db_factory


def test_отчёт_считает_средний_по_первым_попыткам_и_показывает_повтор(client, repeated):
    body = client.get("/api/teacher/sessions/1/report", headers=token(client, "teacher")).json()
    ivanov = next(s for s in body["students"] if s["student_name"] == "Иванов И.И.")

    # Три карточки в базе (одна из общих фикстур не завершена), повтор не в счёт.
    assert ivanov["attempts"] == 3
    assert ivanov["finished"] == 2
    assert ivanov["average_score"] == pytest.approx(0.7)
    assert ivanov["critical"] == 1
    assert ivanov["passed"] is False

    assert len(ivanov["repeats"]) == 1
    repeat = ivanov["repeats"][0]
    assert repeat["first_score"] == 0.5
    assert repeat["repeat_score"] == 0.95
    assert repeat["fixed"] is True

    assert body["repeats_issued"] == 1
    assert body["repeats_finished"] == 1
    assert body["repeats_fixed"] == 1
    assert body["total_attempts"] == 3
    assert any("возвращены повторно: 1" in line for line in body["insights"])


def test_не_исправившийся_повтор_виден_в_отчёте(client, repeated, db_factory):
    with db_factory() as db:
        repeat = db.scalar(select(Attempt).where(Attempt.repeat_of_id.is_not(None)))
        repeat.evaluation.score = 0.3
        db.commit()

    body = client.get("/api/teacher/sessions/1/report", headers=token(client, "teacher")).json()
    ivanov = next(s for s in body["students"] if s["student_name"] == "Иванов И.И.")
    assert ivanov["repeats"][0]["fixed"] is False
    assert body["repeats_fixed"] == 0
    # Средний балл первого прохода от исхода повтора не зависит.
    assert ivanov["average_score"] == pytest.approx(0.7)


def test_сводка_упоминает_повторы():
    notes = report._insights(collections.Counter(), 4, 0.0, 30, (2, 1, 1))
    assert notes[-1] == (
        "Проваленные карточки возвращены повторно: 2. "
        "Из 1 завершённых повторов исправились в 1."
    )
    assert not any("повторно" in n for n in report._insights(collections.Counter(), 4, 0.0, 30))


def test_повторы_попадают_в_выгрузку(client, repeated):
    headers = token(client, "teacher")
    payload = client.get("/api/teacher/sessions/1/report.csv", headers=headers).content
    table = list(csv.reader(io.StringIO(payload.decode("utf-8-sig")), delimiter=";"))

    assert ["Повторных выдач", "1"] in table
    assert ["Исправились после повтора", "1 из 1"] in table
    header = table.index(["Повторные выдачи проваленных карточек"])
    assert table[header + 2] == ["Иванов И.И.", "Застревание в лифте", "50,0", "95,0", "исправился"]

    pdf = client.get("/api/teacher/sessions/1/report.pdf", headers=headers)
    assert pdf.status_code == 200


def test_список_работ_помечает_повтор(client, repeated):
    works = client.get("/api/teacher/sessions/1/works", headers=token(client, "teacher")).json()
    repeats = [w for w in works if w["repeat_of_id"] is not None]
    assert len(repeats) == 1
    assert repeats[0]["repeat_of_id"] in {w["attempt_id"] for w in works}


def test_личный_кабинет_показывает_повтор_отдельно(client, repeated):
    body = client.get("/api/student/progress", headers=token(client, "student")).json()
    # Средний балл — по первому проходу: (0,5 + 0,9) / 2.
    assert body["finished"] == 2
    assert body["average_score"] == pytest.approx(0.7)
    assert body["repeats_finished"] == 1
    assert body["repeats_fixed"] == 1
    repeat = next(w for w in body["works"] if w["is_repeat"])
    assert repeat["repeat_fixed"] is True
    assert any("Повторные выдачи: 1" in line for line in body["advice"])


# --- Настройка занятия преподавателем ----------------------------------------


def test_повтор_включается_при_создании_и_правке_занятия(client):
    headers = token(client, "teacher")
    created = client.post(
        "/api/teacher/sessions",
        json={"title": "Занятие с повтором", "repeat_failed": True},
        headers=headers,
    ).json()
    assert created["repeat_failed"] is True

    patched = client.patch(
        f"/api/teacher/sessions/{created['id']}",
        json={"repeat_failed": False},
        headers=headers,
    ).json()
    assert patched["repeat_failed"] is False

    # По умолчанию повтор выключен: прежние занятия ведут себя как раньше.
    plain = client.post(
        "/api/teacher/sessions", json={"title": "Обычное занятие"}, headers=headers
    ).json()
    assert plain["repeat_failed"] is False


# --- Режим диспетчера ДДС через API ------------------------------------------


def test_диспетчер_получает_проваленную_карточку_повторно(client, db_factory):
    enable_repeat(db_factory)
    headers = token(client, "student")

    # Завершение без единого статуса — «Не оповещено», критическое V1.
    evaluation = client.post("/api/attempts/1/finish", headers=headers).json()
    assert "V1" in [v["code"] for v in evaluation["violations"]]

    cards = client.get("/api/attempts/my", headers=headers).json()
    assert len(cards) == 2
    repeat = next(c for c in cards if c["is_repeat"])
    original = next(c for c in cards if not c["is_repeat"])
    assert repeat["attempt_id"] != original["attempt_id"]
    # Тот же вызов: тип и адрес совпадают, эталон не раскрывается.
    assert repeat["incident_type"] == original["incident_type"]
    assert repeat["address"] == original["address"]
    assert repeat["finished"] is False

    with db_factory() as db:
        row = db.get(Attempt, repeat["attempt_id"])
        assert row.repeat_of_id == 1
        assert row.evaluation is None


def test_повтор_диспетчера_встаёт_в_конец_потока(client, db_factory):
    """При ненулевом интервале карточка назначается на будущее и в ленте её ещё нет."""
    enable_repeat(db_factory, interval=600)
    headers = token(client, "student")
    client.post("/api/attempts/1/finish", headers=headers)

    assert len(client.get("/api/attempts/my", headers=headers).json()) == 1
    with db_factory() as db:
        row = db.scalar(select(Attempt).where(Attempt.repeat_of_id == 1))
        assert row is not None
        assert row.issued_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)


def test_проваленный_повтор_диспетчера_не_возвращается_снова(client, db_factory):
    enable_repeat(db_factory)
    headers = token(client, "student")
    client.post("/api/attempts/1/finish", headers=headers)
    repeat_id = next(
        c["attempt_id"] for c in client.get("/api/attempts/my", headers=headers).json()
        if c["is_repeat"]
    )

    client.post(f"/api/attempts/{repeat_id}/finish", headers=headers)

    assert len(client.get("/api/attempts/my", headers=headers).json()) == 2


def test_зачтённая_карточка_диспетчера_не_возвращается(client, db_factory):
    enable_repeat(db_factory)
    headers = token(client, "student")
    client.post(
        "/api/attempts/1/status",
        json={
            "status": str(S.REJECTED),
            "comment": "Не обслуживаем, информация передана в диспетчерскую «Практика»",
        },
        headers=headers,
    )
    evaluation = client.post("/api/attempts/1/finish", headers=headers).json()
    assert evaluation["score"] == 1.0
    assert len(client.get("/api/attempts/my", headers=headers).json()) == 1


def test_без_флага_у_занятия_повтора_нет(client):
    headers = token(client, "student")
    client.post("/api/attempts/1/finish", headers=headers)
    assert len(client.get("/api/attempts/my", headers=headers).json()) == 1


# --- Режим оператора 112 через API -------------------------------------------


def make_call(db_factory, repeat_failed: bool = True) -> int:
    with db_factory() as db:
        student = db.scalar(select(User).where(User.login == "student"))
        teacher = db.scalar(select(User).where(User.login == "teacher"))
        service = db.scalar(select(DispatchService))
        scenario = Scenario(
            title="Учебный вызов",
            mode=TrainingMode.OPERATOR,
            incident_type="",
            ekp_rule_number=1010101,
            address="Москва, ул. Кировоградская, д. 24",
            description="Горит мусорный контейнер во дворе",
            caller="Иванов И. И., 916-126-34-71",
            target_service=service,
            expected_primary_status=str(S.ACCEPTED),
            deadline_seconds=180,
            author=teacher,
        )
        session = TrainingSession(
            title="Занятие 112",
            mode=TrainingMode.OPERATOR,
            teacher=teacher,
            state=SessionState.ACTIVE,
            pickup_deadline_seconds=30,
            handling_deadline_seconds=180,
            call_interval_seconds=0,
            repeat_failed=repeat_failed,
        )
        attempt = Attempt(
            session=session,
            student=student,
            scenario=scenario,
            issued_at=datetime.now(timezone.utc) - timedelta(seconds=20),
        )
        db.add_all([scenario, session, attempt])
        db.commit()
        return attempt.id


def test_оператор_получает_проваленный_вызов_повторно(client, db_factory):
    attempt_id = make_call(db_factory)
    headers = token(client, "student")

    # Московское происшествие передано на сторону — исход неверен, балл ноль.
    body = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={
            "outcome": "refer",
            "referral_target": "Московская область",
            "address": "Москва, ул. Кировоградская, д. 24",
            "description": "Горит мусор",
        },
        headers=headers,
    )
    assert body.status_code == 200, body.text
    assert body.json()["score"] == 0.0

    calls = client.get("/api/operator/calls/my", headers=headers).json()
    assert [c["is_repeat"] for c in calls] == [False, True]
    repeat = calls[1]
    assert repeat["legend"] == calls[0]["legend"]
    assert repeat["finished"] is False
    assert repeat["chosen_outcome"] is None

    with db_factory() as db:
        row = db.get(Attempt, repeat["attempt_id"])
        assert row.repeat_of_id == attempt_id
        assert row.scenario.mode is TrainingMode.OPERATOR


def test_верно_обработанный_вызов_не_возвращается(client, db_factory):
    attempt_id = make_call(db_factory)
    headers = token(client, "student")
    body = client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={
            "group": "Пожары и задымления",
            "path": ["на улице", "мусор", "открытое пламя"],
            "address": "Москва, ул. Кировоградская, д. 24",
            "description": "Горит мусорный контейнер",
        },
        headers=headers,
    )
    assert body.json()["score"] == 1.0
    assert len(client.get("/api/operator/calls/my", headers=headers).json()) == 1


def test_без_флага_вызов_оператора_не_возвращается(client, db_factory):
    attempt_id = make_call(db_factory, repeat_failed=False)
    headers = token(client, "student")
    client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={"outcome": "reject", "address": "", "description": ""},
        headers=headers,
    )
    assert len(client.get("/api/operator/calls/my", headers=headers).json()) == 1
