"""Живой тест ИИ-endpoints на задаче с классификацией (без ключа — ожидаем 502).

Запуск из backend_new при работающем бэкенде:
    python scripts/smoke_ai_classified.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"null")
        except ValueError:
            return exc.code, None


def main() -> int:
    status, login = call("POST", "/auth/login", body={"username": "admin", "password": "admin123"})
    assert status == 200, f"login: {status}"
    token = login["access_token"]

    status, classes = call("GET", "/event-groups", token)
    assert status == 200 and classes, f"event-groups: {status}"
    ec = classes[0]
    print(f"event class: {ec['id']} {ec.get('name')}")

    status, services = call("GET", "/services", token)
    svc = services[0]
    print(f"service: {svc['id']} {svc.get('name')}")

    status, created = call("POST", "/study-tasks", token, {
        "difficulty": 3,
        "caller_message": "Здравствуйте! Горит балкон на улице Лесной, дом 7, я сосед снизу, не знаю, есть ли кто-то дома.",
        "event_class_id": ec["id"],
        "main_service_id": svc["id"],
        "service_ids": [svc["id"]],
    })
    assert status == 201, f"create: {status} {created}"
    task_id = created["id"]
    print(f"task created: {task_id}")

    try:
        status, ref = call("POST", f"/study-tasks/{task_id}/reference-preview", token, {})
        print(f"reference-preview: {status} {str(ref)[:200]}")
        assert status in (200, 502, 503), status

        status, gen = call("POST", f"/study-tasks/{task_id}/generate", token, {"topic": "пожар на балконе"})
        print(f"generate: {status} {str(gen)[:200]}")
        assert status in (200, 502, 503), status

        status, rep = call("POST", f"/study-tasks/{task_id}/caller-reply", token,
                           {"question": "Что горит?", "turns": []})
        print(f"caller-reply: {status} {str(rep)[:200]}")
        assert status in (200, 502, 503), status

        status, val = call("POST", f"/study-tasks/{task_id}/validate-fields", token,
                           {"content": {"title": "x", "report": "y", "fields": {}, "class_ids": [],
                                        "services": [], "main_service": ""}})
        print(f"validate-fields: {status} {str(val)[:120]}")
        assert status == 422, status
    finally:
        status, _ = call("DELETE", f"/study-tasks/{task_id}", token)
        print(f"cleanup delete: {status}")

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
