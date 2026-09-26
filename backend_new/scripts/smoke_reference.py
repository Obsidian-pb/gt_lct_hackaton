"""Смоук-тест: справочники reference и классификатор catalog (API v1).

Запуск из каталога backend_new:
    .venv\\Scripts\\python.exe scripts/smoke_reference.py
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
        r = await client.post(
            f"{BASE}/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert r.status_code == 200, r.text
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # --- Статусы сценариев: список (сид 3) ---
        r = await client.get(f"{BASE}/scenario-statuses", headers=headers)
        assert r.status_code == 200 and len(r.json()) == 3, r.text
        print("scenario-statuses list OK")

        # Создание
        r = await client.post(
            f"{BASE}/scenario-statuses",
            headers=headers,
            json={"code": "review", "name": "На рассмотрении", "sort_order": 15},
        )
        assert r.status_code == 201, r.text
        status_id = r.json()["id"]
        print("scenario-status create OK")

        # Дубликат кода -> 409
        r = await client.post(
            f"{BASE}/scenario-statuses",
            headers=headers,
            json={"code": "review", "name": "Дубль"},
        )
        assert r.status_code == 409, r.text
        print("duplicate -> 409 OK")

        # Обновление и удаление
        r = await client.patch(
            f"{BASE}/scenario-statuses/{status_id}",
            headers=headers,
            json={"is_active": False},
        )
        assert r.status_code == 200 and r.json()["is_active"] is False, r.text
        r = await client.delete(f"{BASE}/scenario-statuses/{status_id}", headers=headers)
        assert r.status_code == 204, r.text
        print("scenario-status update/delete OK")

        # --- Статусы заявителей и роли обучающихся (только чтение) ---
        r = await client.get(f"{BASE}/applicant-statuses", headers=headers)
        assert r.status_code == 200 and len(r.json()) == 3, r.text
        r = await client.get(f"{BASE}/training-roles", headers=headers)
        assert r.status_code == 200 and len(r.json()) == 3, r.text
        codes = {x["code"] for x in r.json()}
        assert codes == {"operator_112", "dispatcher_dds", "service_dispatcher"}, codes
        print("applicant-statuses + training-roles list OK")

        # --- Службы: CRUD ---
        r = await client.post(
            f"{BASE}/services",
            headers=headers,
            json={"code": "fire", "name": "Пожарная охрана"},
        )
        assert r.status_code == 201, r.text
        service_id = r.json()["id"]
        r = await client.post(
            f"{BASE}/services",
            headers=headers,
            json={"code": "medical", "name": "Скорая медицинская помощь"},
        )
        assert r.status_code == 201, r.text
        r = await client.get(f"{BASE}/services", headers=headers)
        assert r.status_code == 200 and len(r.json()) >= 2, r.text
        r = await client.patch(
            f"{BASE}/services/{service_id}",
            headers=headers,
            json={"description": "101"},
        )
        assert r.status_code == 200 and r.json()["description"] == "101", r.text
        r = await client.delete(f"{BASE}/services/{service_id}", headers=headers)
        assert r.status_code == 204, r.text
        print("services CRUD OK")

        # --- Классификатор: пустые списки на старте ---
        for path in [
            "/classifier/event-types",
            "/classifier/features-1",
            "/classifier/features-2",
            "/classifier/features-3",
            "/classifier/versions",
            "/event-groups",
        ]:
            r = await client.get(f"{BASE}{path}", headers=headers)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text}"
        print("classifier empty lists OK")

        # --- RBAC: студент не может создавать справочники ---
        await client.post(
            f"{BASE}/users",
            headers=headers,
            json={
                "username": "smoke_student",
                "password": "secret123",
                "last_name": "Тестов",
                "first_name": "Студент",
                "role_codes": ["student"],
            },
        )
        r = await client.post(
            f"{BASE}/auth/login",
            json={"username": "smoke_student", "password": "secret123"},
        )
        student_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await client.post(
            f"{BASE}/services",
            headers=student_headers,
            json={"code": "police", "name": "Полиция"},
        )
        assert r.status_code == 403, f"rbac write: {r.status_code}"
        print("RBAC write deny OK")

    print("\nSMOKE REFERENCE/CATALOG: ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())