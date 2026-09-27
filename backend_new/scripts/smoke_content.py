"""Смоук-тест: учебные задачи и сценарии (API v1).

Запуск из каталога backend_new:
    .venv\\Scripts\\python.exe scripts/smoke_content.py
"""

from __future__ import annotations

import asyncio

import httpx

from app.core.seed import seed_default_admin
from app.db.session import async_session_factory
from app.main import app

BASE = "/api/v1"
MARK = "SMOKE:"


async def _cleanup(client: httpx.AsyncClient, headers: dict) -> None:
    """Удаляет данные предыдущих прогонов смоук-теста."""
    r = await client.get(f"{BASE}/study-tasks", headers=headers)
    for task in r.json():
        if task["caller_message"].startswith(MARK):
            await client.delete(f"{BASE}/study-tasks/{task['id']}", headers=headers)
    r = await client.get(f"{BASE}/scenarios", headers=headers)
    for scenario in r.json():
        if scenario["topic"].startswith(MARK):
            await client.delete(f"{BASE}/scenarios/{scenario['id']}", headers=headers)


async def main() -> None:
    async with async_session_factory() as session:
        await seed_default_admin(session)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"{BASE}/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        await _cleanup(client, headers)

        # --- Создание учебной задачи (без классификации) ---
        r = await client.post(
            f"{BASE}/study-tasks",
            headers=headers,
            json={
                "difficulty": 3,
                "caller_message": f"{MARK} Пожар в жилом доме, ул. Ленина, д. 5",
                "aon_phone": "+7-495-111-22-33",
                "caller_full_name": "Иванов Иван Иванович",
                "has_victims": True,
                "etalon_content": {
                    "phone": "+7-495-111-22-33",
                    "applicant": "Иванов Иван Иванович",
                    "address": "ул. Ленина, д. 5",
                },
                "field_schema": [
                    {"code": "phone", "type": "text", "label": "Телефон"},
                    {"code": "address", "type": "text", "label": "Адрес"},
                ],
            },
        )
        assert r.status_code == 201, f"create task: {r.status_code} {r.text}"
        task1 = r.json()
        assert task1["status"] == "draft", task1
        assert task1["etalon_content"]["phone"] == "+7-495-111-22-33", task1
        print("create task OK")

        # --- Вторая задача + фильтры списка ---
        r = await client.post(
            f"{BASE}/study-tasks",
            headers=headers,
            json={"difficulty": 1, "caller_message": f"{MARK} Запах газа в подъезде"},
        )
        task2 = r.json()
        r = await client.get(
            f"{BASE}/study-tasks", headers=headers, params={"difficulty": 3}
        )
        assert r.status_code == 200, r.text
        assert len([t for t in r.json() if t["caller_message"].startswith(MARK)]) == 1, r.text
        r = await client.get(
            f"{BASE}/study-tasks", headers=headers, params={"search": "газ"}
        )
        assert r.status_code == 200 and r.json()[0]["id"] == task2["id"], r.text
        print("task filters OK")

        # --- Утверждение задачи ---
        r = await client.post(
            f"{BASE}/study-tasks/{task1['id']}/approve",
            headers=headers,
            json={"approve": True},
        )
        assert r.status_code == 200 and r.json()["status"] == "approved", r.text
        r = await client.post(
            f"{BASE}/study-tasks/{task2['id']}/approve",
            headers=headers,
            json={"approve": True},
        )
        assert r.status_code == 200 and r.json()["status"] == "approved", r.text
        print("approve tasks OK")

        # --- Создание сценария ---
        r = await client.post(
            f"{BASE}/scenarios",
            headers=headers,
            json={"topic": f"{MARK} Пожары в жилом секторе"},
        )
        assert r.status_code == 201, r.text
        scenario_id = r.json()["id"]
        print("create scenario OK")

        # Добавление утверждённой задачи — OK
        r = await client.post(
            f"{BASE}/scenarios/{scenario_id}/tasks",
            headers=headers,
            json={"study_task_id": task1["id"]},
        )
        assert r.status_code == 200, r.text
        # Повторное добавление — 409
        r = await client.post(
            f"{BASE}/scenarios/{scenario_id}/tasks",
            headers=headers,
            json={"study_task_id": task1["id"]},
        )
        assert r.status_code == 409, r.text
        print("scenario add task OK")

        # --- Список сценариев: task_count ---
        r = await client.get(f"{BASE}/scenarios", headers=headers)
        assert r.status_code == 200, r.text
        scenario = next(s for s in r.json() if s["id"] == scenario_id)
        assert scenario["task_count"] == 1, scenario
        print("scenario list + task_count OK")

        # --- Детали сценария ---
        r = await client.get(f"{BASE}/scenarios/{scenario_id}", headers=headers)
        assert r.status_code == 200 and len(r.json()["tasks"]) == 1, r.text
        print("scenario detail OK")

        # --- Утверждение сценария ---
        r = await client.post(
            f"{BASE}/scenarios/{scenario_id}/approve", headers=headers
        )
        assert r.status_code == 200, r.text
        print("approve scenario OK")

        # --- Обновление и удаление задачи ---
        r = await client.patch(
            f"{BASE}/study-tasks/{task2['id']}",
            headers=headers,
            json={"difficulty": 2, "street": "Московская ул."},
        )
        assert r.status_code == 200 and r.json()["difficulty"] == 2, r.text
        r = await client.delete(f"{BASE}/study-tasks/{task2['id']}", headers=headers)
        assert r.status_code == 204, r.text
        r = await client.get(f"{BASE}/study-tasks/{task2['id']}", headers=headers)
        assert r.status_code == 404, r.text
        print("update/delete task OK")

        # --- Генерация ИИ — заглушка 501 ---
        r = await client.post(
            f"{BASE}/study-tasks/{task1['id']}/generate", headers=headers
        )
        assert r.status_code == 501, r.text
        print("AI stub 501 OK")

        # --- RBAC: студент не может создавать задачи ---
        await client.post(
            f"{BASE}/users",
            headers=headers,
            json={
                "username": "smoke_student2",
                "password": "secret123",
                "last_name": "Тестов",
                "first_name": "Студент",
                "role_codes": ["student"],
            },
        )
        r = await client.post(
            f"{BASE}/auth/login",
            json={"username": "smoke_student2", "password": "secret123"},
        )
        student_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await client.post(
            f"{BASE}/study-tasks",
            headers=student_headers,
            json={"difficulty": 1, "caller_message": "Не положено"},
        )
        assert r.status_code == 403, f"rbac: {r.status_code}"
        # Чтение списка задач студенту доступно (окно 7 ТЗ)
        r = await client.get(f"{BASE}/study-tasks", headers=student_headers)
        assert r.status_code == 200, r.text
        print("RBAC read/write OK")

    print("\nSMOKE CONTENT (TASKS/SCENARIOS): ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())