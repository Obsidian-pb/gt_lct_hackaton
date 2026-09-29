"""Смоук-тест: аутентификация, RBAC и управление пользователями (API v1).

Запуск из каталога backend_new:
    .venv\\Scripts\\python.exe scripts/smoke_auth.py

Использует реальную БД из .env (или DATABASE_URL), тестовые данные удаляются.
"""

from __future__ import annotations

import asyncio

import httpx

from app.core.seed import seed_default_admin
from app.db.session import async_session_factory
from app.main import app

BASE = "/api/v1"


async def main() -> None:
    async with async_session_factory() as session:
        await seed_default_admin(session)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # --- Вход администратора ---
        r = await client.post(
            f"{BASE}/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert r.status_code == 200, f"login: {r.status_code} {r.text}"
        tokens = r.json()
        assert tokens["access_token"] and tokens["refresh_token"]
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        print("login OK")

        # --- /auth/me ---
        r = await client.get(f"{BASE}/auth/me", headers=headers)
        assert r.status_code == 200 and r.json()["username"] == "admin", r.text
        assert {"code": "admin"} in [
            {"code": role["code"]} for role in r.json()["roles"]
        ]
        print("me OK")

        # --- Обновление токенов ---
        r = await client.post(
            f"{BASE}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert r.status_code == 200 and r.json()["access_token"], r.text
        print("refresh OK")

        # --- Создание преподавателя ---
        r = await client.post(
            f"{BASE}/users",
            headers=headers,
            json={
                "username": "smoke_teacher",
                "password": "secret123",
                "last_name": "Тестов",
                "first_name": "Преподаватель",
                "email": "smoke_teacher@example.local",
                "role_codes": ["teacher"],
            },
        )
        assert r.status_code == 201, f"create: {r.status_code} {r.text}"
        user_id = r.json()["id"]
        print("create user OK")

        # --- Список пользователей ---
        r = await client.get(f"{BASE}/users", headers=headers)
        assert r.status_code == 200, r.text
        assert any(u["id"] == user_id for u in r.json()), "user not in list"
        print("list users OK")

        # --- Список ролей ---
        r = await client.get(f"{BASE}/users/roles", headers=headers)
        assert r.status_code == 200, r.text
        codes = {role["code"] for role in r.json()}
        assert {"system_admin", "admin", "teacher", "student"} <= codes, codes
        print("list roles OK")

        # --- Назначение ролей ---
        r = await client.put(
            f"{BASE}/users/{user_id}/roles",
            headers=headers,
            json={"role_codes": ["student", "teacher"]},
        )
        assert r.status_code == 200, r.text
        assert {x["code"] for x in r.json()["roles"]} == {"student", "teacher"}, r.text
        print("assign roles OK")

        # --- RBAC: преподаватель не может управлять пользователями ---
        r = await client.post(
            f"{BASE}/auth/login",
            json={"username": "smoke_teacher", "password": "secret123"},
        )
        t2 = r.json()
        r = await client.get(
            f"{BASE}/users", headers={"Authorization": f"Bearer {t2['access_token']}"}
        )
        assert r.status_code == 403, f"rbac: {r.status_code} {r.text}"
        print("RBAC deny OK")

        # --- Обновление и удаление (мягкое) ---
        r = await client.patch(
            f"{BASE}/users/{user_id}",
            headers=headers,
            json={"phone": "+7-900-000-00-00", "is_active": False},
        )
        assert r.status_code == 200 and r.json()["phone"] == "+7-900-000-00-00", r.text
        r = await client.delete(f"{BASE}/users/{user_id}", headers=headers)
        assert r.status_code == 204, r.text
        r = await client.get(f"{BASE}/users/{user_id}", headers=headers)
        assert r.status_code == 404, f"soft-delete: {r.status_code}"
        print("update + soft-delete OK")

        # --- Плохой пароль ---
        r = await client.post(
            f"{BASE}/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert r.status_code == 401, f"bad password: {r.status_code}"
        print("bad password OK")

        # --- Без токена ---
        r = await client.get(f"{BASE}/auth/me")
        assert r.status_code == 401, f"no token: {r.status_code}"
        print("no token OK")

    print("\nSMOKE AUTH: ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())