"""Кабинет администратора: разделение ролей, учётные записи, журнал аудита."""

import pytest
from sqlalchemy import select

from app.models.audit import AuditAction, AuditEvent
from app.models.user import Role, User
from tests.test_api import token


def test_преподаватель_не_видит_кабинет_администратора(client):
    headers = token(client, "teacher")
    assert client.get("/api/admin/users", headers=headers).status_code == 403


def test_обучающийся_не_видит_кабинет_администратора(client):
    headers = token(client, "student")
    assert client.get("/api/admin/users", headers=headers).status_code == 403


def test_администратор_не_видит_результаты_обучения(admin_client):
    """Ограничение ТЗ: доступ к персональным данным только по необходимости."""
    headers = token(admin_client, "root")
    assert admin_client.get("/api/teacher/catalog", headers=headers).status_code == 403
    assert (
        admin_client.get("/api/teacher/sessions/1/report", headers=headers).status_code == 403
    )


def test_создание_и_блокировка_учётной_записи(admin_client, db_factory):
    headers = token(admin_client, "root")
    created = admin_client.post(
        "/api/admin/users",
        json={
            "login": "newcomer",
            "full_name": "Новиков Пётр Ильич",
            "password": "Training2026",
            "role": "student",
        },
        headers=headers,
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    assert (
        admin_client.post(
            "/api/auth/token", data={"username": "newcomer", "password": "Training2026"}
        ).status_code
        == 200
    )

    blocked = admin_client.patch(
        f"/api/admin/users/{user_id}", json={"is_active": False}, headers=headers
    )
    assert blocked.json()["is_active"] is False
    assert (
        admin_client.post(
            "/api/auth/token", data={"username": "newcomer", "password": "Training2026"}
        ).status_code
        == 403
    )


def test_повторный_логин_отклоняется(admin_client):
    headers = token(admin_client, "root")
    payload = {
        "login": "root",
        "full_name": "Дубликат Логина Петрович",
        "password": "Training2026",
        "role": "student",
    }
    assert admin_client.post("/api/admin/users", json=payload, headers=headers).status_code == 409


def test_администратор_не_блокирует_сам_себя(admin_client, db_factory):
    headers = token(admin_client, "root")
    with db_factory() as db:
        admin_id = db.scalar(select(User).where(User.login == "root")).id
    response = admin_client.patch(
        f"/api/admin/users/{admin_id}", json={"is_active": False}, headers=headers
    )
    assert response.status_code == 409


def test_неудачный_вход_попадает_в_журнал(admin_client, db_factory):
    admin_client.post("/api/auth/token", data={"username": "root", "password": "nope"})
    with db_factory() as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == AuditAction.LOGIN_FAILED)
        ).all()
    assert any(e.actor_login == "root" for e in events)


def test_журнал_доступен_только_администратору(client, admin_client):
    assert client.get("/api/admin/audit", headers=token(client, "teacher")).status_code == 403
    assert (
        admin_client.get("/api/admin/audit", headers=token(admin_client, "root")).status_code
        == 200
    )


@pytest.mark.parametrize("role", [Role.ADMIN, Role.TEACHER, Role.STUDENT])
def test_все_роли_создаются(admin_client, role):
    headers = token(admin_client, "root")
    response = admin_client.post(
        "/api/admin/users",
        json={
            "login": f"user-{role}",
            "full_name": "Тестовый Пользователь Иванович",
            "password": "Training2026",
            "role": str(role),
        },
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["role"] == str(role)
