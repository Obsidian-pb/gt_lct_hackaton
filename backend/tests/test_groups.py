"""Учебные группы: постоянный список обучающихся для набора занятий.

Требование ТЗ к роли преподавателя: «назначать учащимся конкретные задания
и группы». Задания назначаются составом занятия, группа избавляет от того,
чтобы собирать одних и тех же людей заново к каждому занятию.
"""

from app.models.training import SessionState, TrainingSession
from app.models.user import Role, User
from tests.test_api import token


def make_group(client, headers, title="Смена А", **fields) -> dict:
    response = client.post(
        "/api/teacher/groups", json={"title": title, **fields}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def student_ids(client, headers) -> list[int]:
    return [s["id"] for s in client.get("/api/teacher/students", headers=headers).json()]


def test_группа_собирается_из_обучающихся(client):
    headers = token(client, "teacher")
    ids = student_ids(client, headers)
    group = make_group(client, headers, note="Набор сентября", student_ids=ids)
    assert group["note"] == "Набор сентября"
    assert [s["id"] for s in group["students"]] == sorted(ids, key=lambda i: i)


def test_название_группы_не_повторяется(client):
    headers = token(client, "teacher")
    make_group(client, headers)
    again = client.post("/api/teacher/groups", json={"title": "Смена А"}, headers=headers)
    assert again.status_code == 409


def test_в_группу_попадают_только_действующие_обучающиеся(client, db_factory):
    """Заблокированного включать в группу незачем: карточки он всё равно не получит."""
    headers = token(client, "teacher")
    with db_factory() as db:
        blocked = db.query(User).filter_by(login="other").one()
        blocked.is_active = False
        db.commit()
        blocked_id = blocked.id
        active_id = db.query(User).filter_by(login="student").one().id

    group = make_group(client, headers, student_ids=[active_id, blocked_id])
    assert [s["id"] for s in group["students"]] == [active_id]


def test_преподаватель_меняет_состав_группы(client):
    headers = token(client, "teacher")
    ids = student_ids(client, headers)
    group = make_group(client, headers, student_ids=ids)
    updated = client.patch(
        f"/api/teacher/groups/{group['id']}",
        json={"student_ids": ids[:1], "title": "Смена Б"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Смена Б"
    assert len(updated.json()["students"]) == 1


def test_обучающемуся_группы_закрыты(client):
    student = token(client, "student")
    assert client.get("/api/teacher/groups", headers=student).status_code == 403
    assert (
        client.post("/api/teacher/groups", json={"title": "Своя"}, headers=student).status_code
        == 403
    )


def test_состав_занятия_заполняется_группой(client, db_factory):
    headers = token(client, "teacher")
    ids = student_ids(client, headers)
    group = make_group(client, headers, student_ids=ids)
    session = client.post(
        "/api/teacher/sessions", json={"title": "Занятие по группе"}, headers=headers
    ).json()

    updated = client.patch(
        f"/api/teacher/sessions/{session['id']}",
        json={"group_id": group["id"]},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert len(updated.json()["students"]) == len(ids)


def test_правка_группы_не_переписывает_состав_занятия(client, db_factory):
    """Занятие — событие: кто был в составе, тот и остался.

    Иначе отчёт о проведённом занятии менялся бы задним числом при любой
    правке группы.
    """
    headers = token(client, "teacher")
    ids = student_ids(client, headers)
    group = make_group(client, headers, student_ids=ids)
    session = client.post(
        "/api/teacher/sessions", json={"title": "Занятие по группе"}, headers=headers
    ).json()
    client.patch(
        f"/api/teacher/sessions/{session['id']}",
        json={"group_id": group["id"]},
        headers=headers,
    )

    client.patch(
        f"/api/teacher/groups/{group['id']}", json={"student_ids": []}, headers=headers
    )
    after = client.get("/api/teacher/sessions", headers=headers).json()
    same = next(s for s in after if s["id"] == session["id"])
    assert len(same["students"]) == len(ids)


def test_удаление_группы_не_трогает_проведённые_занятия(client, db_factory):
    headers = token(client, "teacher")
    ids = student_ids(client, headers)
    group = make_group(client, headers, student_ids=ids)
    session = client.post(
        "/api/teacher/sessions", json={"title": "Занятие по группе"}, headers=headers
    ).json()
    client.patch(
        f"/api/teacher/sessions/{session['id']}",
        json={"group_id": group["id"]},
        headers=headers,
    )

    assert (
        client.delete(f"/api/teacher/groups/{group['id']}", headers=headers).status_code == 204
    )
    after = client.get("/api/teacher/sessions", headers=headers).json()
    same = next(s for s in after if s["id"] == session["id"])
    assert len(same["students"]) == len(ids)


def test_действия_с_группами_попадают_в_журнал(client):
    teacher = token(client, "teacher")
    admin = token(client, "root")
    group = make_group(client, teacher)
    client.patch(f"/api/teacher/groups/{group['id']}", json={"note": "смена"}, headers=teacher)
    client.delete(f"/api/teacher/groups/{group['id']}", headers=teacher)

    actions = [e["action"] for e in client.get("/api/admin/audit", headers=admin).json()]
    for expected in ("Создана учебная группа", "Изменена учебная группа", "Удалена учебная группа"):
        assert expected in actions, f"в журнале нет события «{expected}»"


def test_состав_нельзя_задать_группой_после_запуска(client, db_factory):
    headers = token(client, "teacher")
    group = make_group(client, headers, student_ids=student_ids(client, headers))
    with db_factory() as db:
        session = db.query(TrainingSession).first()
        session.state = SessionState.ACTIVE
        db.commit()
        session_id = session.id

    response = client.patch(
        f"/api/teacher/sessions/{session_id}", json={"group_id": group["id"]}, headers=headers
    )
    assert response.status_code == 409
