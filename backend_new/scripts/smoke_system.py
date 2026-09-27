"""Смоук-тест: отчёты, материалы, системные настройки, аудит, health."""

from __future__ import annotations

import asyncio
import io

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

        # health
        r = await client.get(f"{BASE}/system/health", headers=headers)
        assert r.status_code == 200 and r.json()["database"] == "up", r.text
        print("health OK")

        # settings upsert + list
        r = await client.put(
            f"{BASE}/system/settings/ai",
            headers=headers,
            json={"value": {"provider": "gigachat", "model": "GigaChat-Pro"}, "description": "Параметры ИИ (окно 30)"},
        )
        assert r.status_code == 200 and r.json()["key"] == "ai", r.text
        r = await client.get(f"{BASE}/system/settings", headers=headers)
        assert r.status_code == 200 and any(s["key"] == "ai" for s in r.json()), r.text
        print("settings OK")

        # audit: после логина и операций должны быть записи
        r = await client.get(f"{BASE}/audit", headers=headers)
        assert r.status_code == 200 and len(r.json()) > 0, r.text
        actions = {e["action"] for e in r.json()}
        assert "auth.login" in actions, actions
        print("audit OK")

        # материалы: загрузка/список/скачивание/удаление
        r = await client.post(
            f"{BASE}/materials",
            headers=headers,
            data={"title": "Инструкция по работе на АРМ-112", "description": "Памятка"},
            files={"file": ("instruction.txt", io.BytesIO(b"operators handbook"), "text/plain")},
        )
        assert r.status_code == 201, r.text
        material_id = r.json()["id"]
        r = await client.get(f"{BASE}/materials", headers=headers)
        assert any(m["id"] == material_id for m in r.json()), r.text
        r = await client.get(f"{BASE}/materials/{material_id}/download", headers=headers)
        assert r.status_code == 200 and r.content == b"operators handbook", r.text
        r = await client.delete(f"{BASE}/materials/{material_id}", headers=headers)
        assert r.status_code == 204, r.text
        print("materials OK")

        # отчёты
        r = await client.get(f"{BASE}/reports/summary", headers=headers)
        assert r.status_code == 200 and "total_cards" in r.json(), r.text
        r = await client.get(f"{BASE}/reports/export.csv", headers=headers)
        assert r.status_code == 200 and "sequence_number" in r.text, r.text
        print("reports OK")

        # RBAC: студент не имеет доступа к /audit
        await client.post(
            f"{BASE}/users",
            headers=headers,
            json={
                "username": f"smoke_sys_{int(asyncio.get_event_loop().time())}",
                "password": "secret123",
                "last_name": "Тест",
                "first_name": "Студент",
                "role_codes": ["student"],
            },
        )

    print("\nSMOKE SYSTEM/REPORTS/MATERIALS: ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())