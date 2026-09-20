"""Доработки кабинета преподавателя.

Четыре требования технического задания: принудительная проверка грамматики
после ручных правок сценария, обратная связь по конкретной работе, критерии
успешности занятия и раздача заданий по уровням сложности.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.llm.base import CommentReview
from app.models.audit import AuditAction, AuditEvent
from app.models.training import (
    Attempt,
    Evaluation,
    Scenario,
    SessionState,
    TrainingMode,
    TrainingSession,
)
from app.models.user import DispatchService, Role, User
from app.services.report import StudentResult
from app.services.sessions import start
from tests.test_api import token


def violation(code: str) -> dict:
    return {"code": code, "title": "", "severity": "", "detail": "", "example": ""}


class FakeProvider:
    """Провайдер с заданным ответом: занятие не должно ходить в сеть."""

    def __init__(self, review: CommentReview) -> None:
        self._review = review

    async def review_comment(self, *, comment, required_points, context):
        self.comment = comment
        return self._review


@pytest.fixture
def graded(db_factory):
    """Завершённая работа обучающегося с выставленной оценкой."""
    with db_factory() as db:
        attempt = db.scalar(select(Attempt))
        attempt.finished_at = datetime.now(timezone.utc)
        attempt.evaluation = Evaluation(
            score=0.8, criteria={}, violations=[], llm_pending=False
        )
        db.add(attempt.evaluation)
        db.commit()
        return attempt.id


# --- Принудительная проверка грамматики -------------------------------------


def test_проверка_грамматики_возвращает_замечания(client, monkeypatch):
    provider = FakeProvider(CommentReview(grammar_issues=["«адресс» — одна «с»"]))
    monkeypatch.setattr("app.api.teacher.get_llm_provider", lambda: provider)

    response = client.post(
        "/api/teacher/scenarios/1/grammar", headers=token(client, "teacher")
    )

    assert response.status_code == 200
    assert response.json()["issues"] == ["«адресс» — одна «с»"]
    # Проверяется именно то, что преподаватель правит руками.
    assert "Застряли в лифте" in provider.comment
    assert "Берзарина" in provider.comment


def test_проверка_грамматики_ничего_не_меняет_в_сценарии(client, monkeypatch, db_factory):
    """Проверка — это чтение: она не переформирует сценарий и не снимает утверждение."""
    monkeypatch.setattr(
        "app.api.teacher.get_llm_provider",
        lambda: FakeProvider(CommentReview(grammar_issues=["замечание"])),
    )
    with db_factory() as db:
        before = db.scalar(select(Scenario))
        description, approved_at = before.description, before.approved_at

    client.post("/api/teacher/scenarios/1/grammar", headers=token(client, "teacher"))

    with db_factory() as db:
        after = db.scalar(select(Scenario))
        assert after.description == description
        assert after.approved_at == approved_at


def test_недоступная_модель_не_выдаётся_за_отсутствие_ошибок(client, monkeypatch):
    """Молчание читалось бы как «ошибок нет» — преподаватель должен знать правду."""
    monkeypatch.setattr(
        "app.api.teacher.get_llm_provider",
        lambda: FakeProvider(CommentReview(available=False)),
    )

    response = client.post(
        "/api/teacher/scenarios/1/grammar", headers=token(client, "teacher")
    )

    assert response.status_code == 503
    assert "Модель недоступна" in response.json()["detail"]


def test_проверка_грамматики_закрыта_обучающемуся(client):
    response = client.post(
        "/api/teacher/scenarios/1/grammar", headers=token(client, "student")
    )
    assert response.status_code == 403


# --- Обратная связь преподавателя по работе ---------------------------------


def test_примечание_преподавателя_видно_обучающемуся(client, graded):
    client.post(
        f"/api/teacher/attempts/{graded}/feedback",
        json={"text": "Комментарий к отказу написан верно, но поздно."},
        headers=token(client, "teacher"),
    )

    body = client.get(
        f"/api/attempts/{graded}/evaluation", headers=token(client, "student")
    ).json()
    assert body["teacher_feedback"] == "Комментарий к отказу написан верно, но поздно."
    assert body["teacher_feedback_by"] == "Преподаватель"
    assert body["teacher_feedback_at"] is not None


def test_примечание_видно_в_личном_кабинете(client, graded):
    client.post(
        f"/api/teacher/attempts/{graded}/feedback",
        json={"text": "Разберите памятку по непрофильным вызовам."},
        headers=token(client, "teacher"),
    )

    body = client.get("/api/student/progress", headers=token(client, "student")).json()
    work = next(w for w in body["works"] if w["attempt_id"] == graded)
    assert work["teacher_feedback"] == "Разберите памятку по непрофильным вызовам."
    assert work["teacher_feedback_by"] == "Преподаватель"


def test_примечание_попадает_в_журнал_аудита(client, graded, db_factory):
    """Результат обучения изменён — по ТЗ это обязано остаться в журнале."""
    client.post(
        f"/api/teacher/attempts/{graded}/feedback",
        json={"text": "Работа зачтена."},
        headers=token(client, "teacher"),
    )

    with db_factory() as db:
        event = db.scalar(
            select(AuditEvent).where(AuditEvent.action == AuditAction.FEEDBACK_LEFT)
        )
        assert event is not None
        assert event.object_id == graded
        assert event.actor_login == "teacher"
        assert event.detail["обучающийся"] == "Иванов И.И."


def test_примечание_к_незавершённой_работе_отклоняется(client):
    """Оценки ещё нет — комментировать нечего, и примечание некуда положить."""
    response = client.post(
        "/api/teacher/attempts/1/feedback",
        json={"text": "Пока нечего оценивать."},
        headers=token(client, "teacher"),
    )
    assert response.status_code == 409


def test_обучающийся_не_комментирует_работы(client, graded):
    response = client.post(
        f"/api/teacher/attempts/{graded}/feedback",
        json={"text": "Сам себе поставлю зачёт."},
        headers=token(client, "student"),
    )
    assert response.status_code == 403


def test_список_работ_занятия_показывает_кому_уже_ответили(client, graded):
    headers = token(client, "teacher")
    client.post(
        f"/api/teacher/attempts/{graded}/feedback",
        json={"text": "Норматив нарушен дважды."},
        headers=headers,
    )

    works = client.get("/api/teacher/sessions/1/works", headers=headers).json()
    assert [w["attempt_id"] for w in works] == [graded]
    assert works[0]["student_name"] == "Иванов И.И."
    assert works[0]["teacher_feedback"] == "Норматив нарушен дважды."


# --- Критерии успешности занятия --------------------------------------------


def test_критерии_успешности_задаются_при_создании_и_правке(client):
    headers = token(client, "teacher")

    created = client.post(
        "/api/teacher/sessions",
        json={"title": "Занятие с порогом", "pass_score": 0.8, "max_critical_violations": 2},
        headers=headers,
    ).json()
    assert created["pass_score"] == 0.8
    assert created["max_critical_violations"] == 2

    patched = client.patch(
        f"/api/teacher/sessions/{created['id']}",
        json={"pass_score": 0.6},
        headers=headers,
    ).json()
    assert patched["pass_score"] == 0.6


def test_порог_выше_единицы_не_принимается(client):
    response = client.post(
        "/api/teacher/sessions",
        json={"title": "Невозможный порог", "pass_score": 1.5},
        headers=token(client, "teacher"),
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "scores,critical,pass_score,max_critical,expected",
    [
        ([0.9, 0.8], 0, 0.7, 0, True),
        ([0.6, 0.5], 0, 0.7, 0, False),
        # Балл выше порога, но критическое нарушение сверх допустимого:
        # служба не выехала бы на происшествие — занятие не зачтено.
        ([0.9, 0.9], 1, 0.7, 0, False),
        ([0.9, 0.9], 1, 0.7, 1, True),
    ],
)
def test_зачёт_считается_по_баллу_и_критическим_нарушениям(
    scores, critical, pass_score, max_critical, expected
):
    result = StudentResult(1, "Иванов И.И.", finished=len(scores), scores=scores,
                           critical=critical)
    assert result.passed(pass_score, max_critical) is expected


def test_без_завершённых_работ_зачёт_не_решается():
    """Обучающийся, до которого карточки не дошли, не «не сдал»."""
    assert StudentResult(1, "Иванов И.И.", attempts=3).passed(0.7, 0) is None


def test_отчёт_показывает_кто_прошёл_порог(client, db_factory):
    with db_factory() as db:
        session = db.scalar(select(TrainingSession))
        session.pass_score = 0.75
        session.max_critical_violations = 0
        student = db.scalar(select(User).where(User.login == "student"))
        other = db.scalar(select(User).where(User.login == "other"))
        scenario = db.scalar(select(Scenario))
        for owner, score, codes in ((student, 0.9, []), (other, 0.9, ["V1"])):
            attempt = Attempt(
                session=session,
                student=owner,
                scenario=scenario,
                issued_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                finished_at=datetime.now(timezone.utc),
            )
            attempt.evaluation = Evaluation(
                score=score,
                criteria={},
                violations=[violation(c) for c in codes],
                llm_pending=False,
            )
            db.add(attempt)
        db.commit()

    body = client.get("/api/teacher/sessions/1/report", headers=token(client, "teacher")).json()
    by_name = {s["student_name"]: s for s in body["students"]}

    assert body["pass_score"] == 0.75
    assert by_name["Иванов И.И."]["passed"] is True
    # V1 — критическое нарушение, допустимо ноль.
    assert by_name["Петров П.П."]["passed"] is False
    assert by_name["Петров П.П."]["critical"] == 1
    assert body["passed_students"] == 1
    assert body["failed_students"] == 1


# --- Раздача заданий по уровням сложности -----------------------------------


def test_сценарии_отбираются_по_уровню_сложности(client, db_factory):
    with db_factory() as db:
        simple = db.scalar(select(Scenario))
        simple.difficulty = 1
        hard = Scenario(
            title="Пожар в многоквартирном доме",
            incident_type="пожар",
            address="Москва",
            description="Задымление на этаже",
            target_service=simple.target_service,
            expected_primary_status="Принята",
            author=db.scalar(select(User).where(User.login == "teacher")),
            difficulty=3,
        )
        db.add(hard)
        db.commit()

    headers = token(client, "teacher")
    assert len(client.get("/api/teacher/scenarios", headers=headers).json()) == 2

    selected = client.get("/api/teacher/scenarios?difficulty=3", headers=headers).json()
    assert [s["title"] for s in selected] == ["Пожар в многоквартирном доме"]


def test_карточки_поступают_от_простых_к_сложным():
    """Раздача по уровням: внутри уровня порядок у каждого остаётся своим."""
    service = DispatchService(name="ДДС района", ekp_name="Территориальные ОИВ")
    teacher = User(login="t", full_name="Т", hashed_password="x", role=Role.TEACHER)
    students = [
        User(login=f"s{i}", full_name=f"Обучающийся {i}", hashed_password="x",
             role=Role.STUDENT, service=service)
        for i in (1, 2)
    ]
    scenarios = []
    # По две карточки каждого уровня: без пар нельзя проверить, что порядок
    # внутри уровня всё ещё перемешивается.
    for level in (3, 1, 2, 3, 1, 2):
        scenario = Scenario(
            title=f"Сценарий уровня {level}",
            mode=TrainingMode.DISPATCHER,
            incident_type="тип",
            address="Москва",
            description="описание",
            target_service=service,
            expected_primary_status="Принята",
            author=teacher,
            difficulty=level,
        )
        scenario.approved_at = datetime(2026, 9, 16, tzinfo=timezone.utc)
        scenarios.append(scenario)

    session = TrainingSession(
        title="Занятие", teacher=teacher, state=SessionState.DRAFT,
        pickup_deadline_seconds=30, handling_deadline_seconds=180,
        call_interval_seconds=20,
    )
    session.id = 1
    for index, student in enumerate(students, start=1):
        student.id = index
    session.students = students
    session.scenarios = scenarios

    created = start(session)
    by_student: dict[int, list] = {}
    for attempt in created:
        by_student.setdefault(attempt.student.id, []).append(attempt.scenario)

    assert len(by_student) == 2
    orders = []
    for issued in by_student.values():
        levels = [s.difficulty for s in issued]
        assert levels == sorted(levels)
        orders.append([id(s) for s in issued])
    # Порядок задаётся зерном из номеров занятия и обучающегося, поэтому
    # различие воспроизводимо, а не случайно от запуска к запуску.
    assert orders[0] != orders[1]
