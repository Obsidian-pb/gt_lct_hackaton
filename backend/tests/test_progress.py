"""Личный кабинет обучающегося: статистика, история ошибок, рекомендации."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.models.training import (
    Attempt,
    Evaluation,
    Scenario,
    SessionState,
    StatusEvent,
    TrainingMode,
    TrainingSession,
)
from app.models.user import DispatchService, User
from app.services import progress
from app.services.response_status import ResponseStatus as S


def token(client: TestClient, login: str) -> dict:
    response = client.post("/api/auth/token", data={"username": login, "password": "pwd"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def violation(code: str) -> dict:
    return {"code": code, "title": "", "severity": "", "detail": "", "example": ""}


@pytest.fixture
def filled(db_factory):
    """Добавляет обучающемуся историю: шесть завершённых работ с ошибками."""
    with db_factory() as db:
        student = db.query(User).filter_by(login="student").one()
        session = db.query(TrainingSession).first()
        scenario = db.query(Scenario).first()
        started = datetime.now(timezone.utc) - timedelta(hours=2)

        # Баллы растут: первая половина слабее второй — должна появиться
        # положительная динамика.
        scores = [0.4, 0.5, 0.6, 0.8, 0.9, 1.0]
        for number, score in enumerate(scores):
            attempt = Attempt(
                session=session,
                student=student,
                scenario=scenario,
                issued_at=started + timedelta(minutes=number * 5),
                opened_at=started + timedelta(minutes=number * 5, seconds=10),
                finished_at=started + timedelta(minutes=number * 5, seconds=100),
            )
            # Первый статус позже норматива в 30 секунд — кроме последних двух.
            attempt.events.append(
                StatusEvent(
                    status=str(S.ACCEPTED),
                    comment=None,
                    elapsed_seconds=45.0 if number < 4 else 12.0,
                )
            )
            codes = ["V8"] if number < 4 else []
            if number < 2:
                codes.append("V4")
            attempt.evaluation = Evaluation(
                score=score,
                criteria={},
                violations=[violation(c) for c in codes],
                grammar_issues=["адресс"] if number == 0 else [],
                llm_pending=False,
            )
            db.add(attempt)
        db.commit()
    return db_factory


def test_пустой_кабинет_подсказывает_с_чего_начать(client):
    body = client.get("/api/student/progress", headers=token(client, "student")).json()
    assert body["finished"] == 0
    assert body["average_score"] == 0.0
    assert body["trend"] is None
    assert "Завершённых работ пока нет" in body["advice"][0]


def test_статистика_считается_по_всем_занятиям(client, filled):
    body = client.get("/api/student/progress", headers=token(client, "student")).json()
    assert body["finished"] == 6
    assert body["average_score"] == pytest.approx(0.7, abs=0.001)
    assert body["overdue_pickup"] == 4
    assert body["grammar_issues"] == 1
    assert body["student_name"] == "Иванов И.И."


def test_история_ошибок_упорядочена_по_тяжести(client, filled):
    body = client.get("/api/student/progress", headers=token(client, "student")).json()
    codes = [m["code"] for m in body["mistakes"]]
    # V8 — критическое (опоздание), V4 — существенное: критические выше.
    assert codes == ["V8", "V4"]
    assert body["mistakes"][0]["count"] == 4
    assert body["mistakes"][0]["title"]
    assert body["mistakes"][0]["example"]


def test_динамика_показывает_рост(client, filled):
    body = client.get("/api/student/progress", headers=token(client, "student")).json()
    # Первая половина 0,4–0,6, вторая 0,8–1,0 — разница около 0,4.
    assert body["trend"] == pytest.approx(0.4, abs=0.001)


def test_динамика_не_считается_на_малой_выборке(db_factory):
    """Три результата различаются случайно — говорить о прогрессе рано."""
    with db_factory() as db:
        attempts = db.query(Attempt).all()
        assert progress.build(attempts).trend is None


def test_рекомендации_опираются_на_собственные_ошибки(client, filled):
    body = client.get("/api/student/progress", headers=token(client, "student")).json()
    joined = " ".join(body["advice"])
    assert "Норматив взятия карточки в работу нарушен" in joined
    assert any(m["title"] in joined for m in body["mistakes"])


def test_история_работ_свежие_сверху(client, filled):
    body = client.get("/api/student/progress", headers=token(client, "student")).json()
    finished = [w["finished_at"] for w in body["works"]]
    assert finished == sorted(finished, reverse=True)
    assert body["works"][0]["score"] == 1.0


def test_обучающийся_не_видит_чужой_прогресс(client, filled):
    other = client.get(
        "/api/student/progress",
        params={"student_id": 1},
        headers=token(client, "other"),
    )
    assert other.status_code == 403


def test_преподаватель_видит_прогресс_обучающегося(client, filled, db_factory):
    with db_factory() as db:
        student_id = db.query(User).filter_by(login="student").one().id
    body = client.get(
        "/api/student/progress",
        params={"student_id": student_id},
        headers=token(client, "teacher"),
    )
    assert body.status_code == 200
    assert body.json()["finished"] == 6


def test_администратору_персональные_данные_закрыты(client, filled, db_factory):
    """ТЗ ограничивает администратора в доступе к персональным данным."""
    with db_factory() as db:
        student_id = db.query(User).filter_by(login="student").one().id
    response = client.get(
        "/api/student/progress",
        params={"student_id": student_id},
        headers=token(client, "root"),
    )
    assert response.status_code == 403


def test_разрез_по_режимам_обучения(client, filled, db_factory):
    """Занятия оператора 112 и диспетчера ДДС считаются отдельно."""
    with db_factory() as db:
        student = db.query(User).filter_by(login="student").one()
        teacher = db.query(User).filter_by(login="teacher").one()
        service = db.query(DispatchService).one()
        call = Scenario(
            title="Билет 1, вызов 1",
            mode=TrainingMode.OPERATOR,
            incident_type="",
            ekp_rule_number=1010101,
            address="Москва",
            description="Возгорание мусора",
            caller="Аноним",
            target_service=service,
            expected_primary_status=str(S.ACCEPTED),
            author=teacher,
        )
        session = TrainingSession(
            title="Занятие 112",
            teacher=teacher,
            mode=TrainingMode.OPERATOR,
            state=SessionState.ACTIVE,
            pickup_deadline_seconds=30,
            handling_deadline_seconds=180,
        )
        now = datetime.now(timezone.utc)
        attempt = Attempt(
            session=session,
            student=student,
            scenario=call,
            issued_at=now - timedelta(seconds=120),
            opened_at=now - timedelta(seconds=110),
            finished_at=now,
        )
        attempt.evaluation = Evaluation(
            score=0.5, criteria={}, violations=[violation("O3")], llm_pending=False
        )
        db.add_all([call, session, attempt])
        db.commit()

    body = client.get("/api/student/progress", headers=token(client, "student")).json()
    modes = {m["mode"]: m for m in body["by_mode"]}
    assert set(modes) == {str(TrainingMode.DISPATCHER), str(TrainingMode.OPERATOR)}
    assert modes[str(TrainingMode.OPERATOR)]["finished"] == 1
    assert modes[str(TrainingMode.DISPATCHER)]["finished"] == 6
    # Нарушение из каталога оператора попадает в общую историю ошибок.
    assert "O3" in [m["code"] for m in body["mistakes"]]
