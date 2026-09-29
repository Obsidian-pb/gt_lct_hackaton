"""Смоук-тест полного учебного цикла: тренировка, эмулятор, диспетчеры (API v1).

Покрывает Сценарии 3 и 4 ТЗ:
  преподаватель -> тренировка -> активация ->
  оператор-112 (сессия, задача, карточка, машинная оценка) ->
  диспетчер ДДС (принял, направил в службу) ->
  диспетчер службы (отработал) -> итоговая оценка -> прогресс.

Запуск из каталога backend_new:
    .venv\\Scripts\\python.exe scripts/smoke_training.py
"""

from __future__ import annotations

import asyncio
import time

import httpx

from app.core.seed import seed_default_admin
from app.db.session import async_session_factory
from app.main import app

BASE = "/api/v1"
MARK = "SMOKE"
SUFFIX = str(int(time.time()))


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

        # --- Пользователи с уникальными логинами ---
        tokens: dict[str, str] = {}
        for key, role in [
            ("teacher", "teacher"),
            ("operator", "student"),
            ("dds", "student"),
            ("service", "student"),
        ]:
            username = f"smoke_{key}_{SUFFIX}"
            r = await client.post(
                f"{BASE}/users",
                headers=headers,
                json={
                    "username": username,
                    "password": "secret123",
                    "last_name": f"{username}",
                    "first_name": "Тест",
                    "role_codes": [role],
                },
            )
            assert r.status_code == 201, r.text
            tokens[key] = username
        r = await client.get(f"{BASE}/users", headers=headers)
        users = {u["username"]: u["id"] for u in r.json()}
        user_ids = {key: users[name] for key, name in tokens.items()}
        print("users OK")

        async def login(username: str) -> dict[str, str]:
            r = await client.post(
                f"{BASE}/auth/login",
                json={"username": username, "password": "secret123"},
            )
            assert r.status_code == 200, r.text
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        # Служба для диспетчера службы
        r = await client.post(
            f"{BASE}/services",
            headers=headers,
            json={"code": f"{MARK.lower()}_{SUFFIX}", "name": "Smoke-служба"},
        )
        service_id = r.json()["id"]

        # --- Учебная задача + сценарий ---
        r = await client.post(
            f"{BASE}/study-tasks",
            headers=headers,
            json={
                "difficulty": 2,
                "caller_message": f"{MARK}: задымление в подъезде, ул. Тестовая, 10",
                "aon_phone": "+7-495-000-00-01",
                "etalon_content": {
                    "phone": "+7-495-000-00-01",
                    "address": "ул. Тестовая, 10",
                    "category": "Пожар",
                },
            },
        )
        task_id = r.json()["id"]
        await client.post(
            f"{BASE}/study-tasks/{task_id}/approve",
            headers=headers,
            json={"approve": True},
        )
        r = await client.post(
            f"{BASE}/scenarios",
            headers=headers,
            json={"topic": f"{MARK}: Пожары {SUFFIX}"},
        )
        scenario_id = r.json()["id"]
        r = await client.post(
            f"{BASE}/scenarios/{scenario_id}/tasks",
            headers=headers,
            json={"study_task_id": task_id},
        )
        assert r.status_code == 200, r.text
        r = await client.post(f"{BASE}/scenarios/{scenario_id}/approve", headers=headers)
        assert r.status_code == 200, r.text
        print("task + scenario OK")

        # --- Роли обучающихся (сид) ---
        r = await client.get(f"{BASE}/training-roles", headers=headers)
        roles = {x["code"]: x["id"] for x in r.json()}

        # --- Тренировка ---
        r = await client.post(
            f"{BASE}/trainings",
            headers=headers,
            json={
                "title": f"{MARK}: тренировка {SUFFIX}",
                "difficulty": "medium",
                "mode": "training",
                "scenario_ids": [scenario_id],
            },
        )
        assert r.status_code == 201, r.text
        training_id = r.json()["id"]
        print("create training OK")

        # Назначение участников
        await client.post(
            f"{BASE}/trainings/{training_id}/participants",
            headers=headers,
            json={
                "user_id": user_ids["operator"],
                "training_role_id": roles["operator_112"],
            },
        )
        await client.post(
            f"{BASE}/trainings/{training_id}/participants",
            headers=headers,
            json={
                "user_id": user_ids["dds"],
                "training_role_id": roles["dispatcher_dds"],
            },
        )
        r = await client.post(
            f"{BASE}/trainings/{training_id}/participants",
            headers=headers,
            json={
                "user_id": user_ids["service"],
                "training_role_id": roles["service_dispatcher"],
                "service_id": service_id,
            },
        )
        assert r.status_code == 201, r.text
        print("participants OK")

        # Активация
        r = await client.post(
            f"{BASE}/trainings/{training_id}/activate", headers=headers
        )
        assert r.status_code == 200 and r.json()["status"] == "active", r.text
        print("activate training OK")

        # --- Оператор-112: сессия и карточка ---
        op_headers = await login(tokens["operator"])
        r = await client.post(
            f"{BASE}/sessions/start",
            headers=op_headers,
            json={"training_id": training_id},
        )
        assert r.status_code == 200, r.text
        session_id = r.json()["id"]
        print("session start OK")

        r = await client.get(
            f"{BASE}/sessions/{session_id}/next-task", headers=op_headers
        )
        assert r.status_code == 200 and r.json()["study_task_id"] == task_id, r.text
        print("next-task OK")

        r = await client.post(
            f"{BASE}/sessions/{session_id}/accept-call",
            headers=op_headers,
            json={"study_task_id": task_id},
        )
        assert r.status_code == 200 and r.json()["status"] == "draft", r.text
        card_id = r.json()["id"]
        print("accept call OK")

        r = await client.patch(
            f"{BASE}/cards/{card_id}/content",
            headers=op_headers,
            json={"content": {"phone": "+7-495-000-00-01", "address": "другой адрес"}},
        )
        assert r.status_code == 200, r.text
        r = await client.post(
            f"{BASE}/cards/{card_id}/submit",
            headers=op_headers,
            json={
                "content": {
                    "phone": "+7-495-000-00-01",
                    "address": "ул. Тестовая, 10",
                    "category": "Пожар",
                }
            },
        )
        assert r.status_code == 200, r.text
        submitted = r.json()
        assert submitted["status"] == "submitted", submitted
        assert submitted["machine_score"] == 100.0, submitted
        print(f"submit card OK, machine_score={submitted['machine_score']}")

        # --- Диспетчер ДДС: контроль карточек (окно 36) ---
        dds_headers = await login(tokens["dds"])
        r = await client.get(
            f"{BASE}/dispatcher/cards",
            headers=dds_headers,
            params={"training_id": training_id},
        )
        assert r.status_code == 200 and len(r.json()) == 1, r.text
        r = await client.post(f"{BASE}/cards/{card_id}/accept", headers=dds_headers)
        assert r.status_code == 200 and r.json()["status"] == "accepted", r.text
        r = await client.post(
            f"{BASE}/cards/{card_id}/route",
            headers=dds_headers,
            json={"service_id": service_id},
        )
        assert r.status_code == 200 and r.json()["status"] == "routed", r.text
        print("dispatcher DDS accept+route OK")

        # --- Диспетчер службы ---
        svc_headers = await login(tokens["service"])
        r = await client.get(
            f"{BASE}/dispatcher/cards",
            headers=svc_headers,
            params={"training_id": training_id},
        )
        assert r.status_code == 200 and len(r.json()) == 1, r.text
        r = await client.post(f"{BASE}/cards/{card_id}/process", headers=svc_headers)
        assert r.status_code == 200 and r.json()["status"] == "processed", r.text
        print("service dispatcher process OK")

        # --- Итоговая оценка преподавателя (окно 15) ---
        tch_headers = await login(tokens["teacher"])
        r = await client.post(
            f"{BASE}/cards/{card_id}/grade",
            headers=tch_headers,
            json={"final_score": 90.0},
        )
        assert r.status_code == 200 and r.json()["final_score"] == 90.0, r.text
        print("grade card OK")

        # --- Прогресс тренировки ---
        r = await client.get(
            f"{BASE}/trainings/{training_id}/progress", headers=headers
        )
        assert r.status_code == 200, r.text
        progress = r.json()
        assert progress["total_cards"] == 1 and progress["submitted_cards"] == 1, progress
        assert progress["evaluated_cards"] == 1, progress
        print("progress OK")

        # --- Список тренировок студента (только назначенные) ---
        r = await client.get(f"{BASE}/trainings", headers=op_headers)
        assert r.status_code == 200, r.text
        assert any(t["id"] == training_id for t in r.json()), r.text
        print("student sees own training OK")

        # --- Завершение тренировки ---
        r = await client.post(
            f"{BASE}/trainings/{training_id}/finish", headers=headers
        )
        assert r.status_code == 200 and r.json()["status"] == "finished", r.text
        print("finish training OK")

    print("\nSMOKE TRAINING (full cycle): ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())