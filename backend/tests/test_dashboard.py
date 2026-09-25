"""Стартовые сводки: главная преподавателя и главная администратора.

Сводки только читают. Проверяется, что цифры на них совпадают с тем, что
преподаватель увидит, открыв занятие или отчёт: средний балл — по первым
попыткам, зачёт — по критериям занятия, ход занятия — тем же счётом,
что и монитор.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.training import (
    Attempt,
    Evaluation,
    Scenario,
    SessionState,
    TrainingMode,
    TrainingSession,
)
from app.models.user import DispatchService, User
from app.services.response_status import ResponseStatus as S
from tests.test_api import token


def violation(code: str) -> dict:
    return {"code": code, "title": "", "severity": "", "detail": "", "example": ""}


def make_work(
    db_factory,
    *,
    score: float,
    session_title: str = "Занятие 112",
    finished_ago: timedelta = timedelta(minutes=5),
    repeat_of: int | None = None,
    violations: list[dict] | None = None,
    feedback: str | None = None,
    student_login: str = "student",
) -> int:
    """Заводит завершённую работу с оценкой и возвращает номер попытки.

    Занятие с таким названием переиспользуется: несколько работ одного
    занятия нужны, чтобы проверить ленту и повторные выдачи.
    """
    with db_factory() as db:
        student = db.query(User).filter_by(login=student_login).one()
        teacher = db.query(User).filter_by(login="teacher").one()
        service = db.query(DispatchService).one()
        session = db.scalar(
            select(TrainingSession).where(TrainingSession.title == session_title)
        )
        if session is None:
            session = TrainingSession(
                title=session_title,
                mode=TrainingMode.OPERATOR,
                teacher=teacher,
                state=SessionState.FINISHED,
                pickup_deadline_seconds=30,
                handling_deadline_seconds=180,
            )
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
            approved_at=datetime.now(timezone.utc),
            author=teacher,
        )
        finished_at = datetime.now(timezone.utc) - finished_ago
        attempt = Attempt(
            session=session,
            student=student,
            scenario=scenario,
            repeat_of_id=repeat_of,
            issued_at=finished_at - timedelta(minutes=3),
            opened_at=finished_at - timedelta(minutes=2),
            finished_at=finished_at,
        )
        evaluation = Evaluation(
            attempt=attempt,
            score=score,
            criteria={},
            violations=violations or [],
            llm_pending=False,
            teacher_feedback=feedback,
        )
        db.add_all([scenario, session, attempt, evaluation])
        db.commit()
        return attempt.id


# --- Главная преподавателя ---------------------------------------------------


def test_сводка_преподавателя_на_данных_сида(client):
    body = client.get("/api/teacher/dashboard", headers=token(client, "teacher")).json()

    assert body["active_sessions"] == 1
    assert body["students_total"] == 2
    # Сценарий сида не утверждён — он и ждёт утверждения.
    assert body["scenarios_pending"] == 1
    assert body["groups_total"] == 0
    assert body["works_7d"] == 0
    # Работ нет — среднее не выдумывается нулём: ноль читался бы как провал.
    assert body["average_score_7d"] is None
    assert body["passed_share_7d"] is None
    assert body["feedback_missing"] == 0
    assert body["recent_works"] == []


def test_идущее_занятие_считается_как_в_мониторе(client):
    headers = token(client, "teacher")
    body = client.get("/api/teacher/dashboard", headers=headers).json()
    monitor = client.get("/api/teacher/sessions/1/monitor", headers=headers).json()

    assert [s["id"] for s in body["sessions"]] == [1]
    row = body["sessions"][0]
    assert row["title"] == "Занятие 1"
    assert row["mode"] == "dispatcher"
    # Одна карточка сида уже поступила, но не обработана — как и в мониторе.
    assert (row["issued"], row["finished"]) == (monitor["issued"], monitor["finished"]) == (1, 0)


def test_средний_балл_считается_только_по_первым_попыткам(client, db_factory):
    """Повтор проваленной карточки в средний балл первого прохода не входит.

    Иначе разбор ошибки по горячим следам поднимал бы средний балл группы,
    и сводка расходилась бы с отчётом занятия.
    """
    first = make_work(db_factory, score=0.4)
    make_work(db_factory, score=1.0, repeat_of=first)
    make_work(db_factory, score=0.8, student_login="other")

    body = client.get("/api/teacher/dashboard", headers=token(client, "teacher")).json()

    # В число работ входят все три: повтор — тоже завершённая работа.
    assert body["works_7d"] == 3
    assert body["average_score_7d"] == pytest.approx(0.6)
    # Зачтена одна из двух первых попыток: 0.4 ниже порога занятия 0.7.
    assert body["passed_share_7d"] == pytest.approx(0.5)


def test_критическое_нарушение_лишает_зачёта_независимо_от_балла(client, db_factory):
    make_work(db_factory, score=0.95, violations=[violation("O1")])

    body = client.get("/api/teacher/dashboard", headers=token(client, "teacher")).json()

    assert body["passed_share_7d"] == 0.0
    assert body["recent_works"][0]["critical"] == 1


def test_работы_без_примечания_и_лента_последних(client, db_factory):
    old = make_work(db_factory, score=0.9, finished_ago=timedelta(days=8))
    answered = make_work(
        db_factory, score=0.7, feedback="Хорошо.", finished_ago=timedelta(hours=2)
    )
    fresh = make_work(db_factory, score=0.5, student_login="other")

    body = client.get("/api/teacher/dashboard", headers=token(client, "teacher")).json()

    # Работа восьмидневной давности за горизонт сводки не попадает.
    assert body["works_7d"] == 2
    assert body["feedback_missing"] == 1
    # Лента — по всем срокам, свежие первыми; в ней видно, кому уже ответили.
    assert [w["attempt_id"] for w in body["recent_works"]] == [fresh, answered, old]
    work = body["recent_works"][0]
    assert work["student_name"] == "Петров П.П."
    assert work["scenario_title"] == "Учебный вызов"
    assert work["session_title"] == "Занятие 112"
    assert work["score"] == 0.5
    assert work["has_feedback"] is False
    assert body["recent_works"][1]["has_feedback"] is True


def test_лента_последних_работ_ограничена(client, db_factory):
    for _ in range(10):
        make_work(db_factory, score=0.8)

    body = client.get("/api/teacher/dashboard", headers=token(client, "teacher")).json()

    assert body["works_7d"] == 10
    assert len(body["recent_works"]) == 8


@pytest.mark.parametrize("логин", ["student", "root"])
def test_сводка_преподавателя_закрыта_остальным(client, логин):
    """Администратору — тоже: в сводке баллы обучающихся, а они ему закрыты по ТЗ."""
    response = client.get("/api/teacher/dashboard", headers=token(client, логин))
    assert response.status_code == 403


# --- Главная администратора --------------------------------------------------


def test_сводка_администратора_собирает_счётчики_состояние_и_журнал(admin_client):
    headers = token(admin_client, "root")
    body = admin_client.get("/api/admin/dashboard", headers=headers).json()

    assert body["system"]["users_total"] == 4
    assert body["system"]["scenarios_total"] == 1
    assert body["health"]["database"]["ok"] is True
    assert body["health"]["llm"]["provider"] == "stub"
    # Вход администратора уже попал в журнал — он и есть последнее событие.
    assert body["audit"][0]["action"] == "Вход в систему"
    assert body["audit"][0]["actor_login"] == "root"
    assert len(body["audit"]) <= 5
    assert body["errors"] == []


def test_сводка_администратора_без_результатов_обучения(admin_client):
    """Ограничение ТЗ: администратор не видит оценок — и сводка их не отдаёт."""
    body = admin_client.get("/api/admin/dashboard", headers=token(admin_client, "root")).json()
    assert "score" not in str(body)
    assert "works" not in body


def test_сводка_администратора_закрыта_преподавателю(client):
    response = client.get("/api/admin/dashboard", headers=token(client, "teacher"))
    assert response.status_code == 403
