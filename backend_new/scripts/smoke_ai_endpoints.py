"""Smoke-тест ИИ-endpoints без ключа провайдера (ожидаемые 502/503/422).

Запуск из backend_new (нужен запущенный бэкенд и БД):
    python scripts/smoke_ai_endpoints.py [base_url]
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/api/v1"


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"null")
        except ValueError:
            return exc.code, None


def main() -> int:
    status, login = call("POST", "/auth/login", body={"username": "admin", "password": "admin123"})
    assert status == 200, f"login: {status} {login}"
    token = login["access_token"]
    print("login: OK")

    status, payload = call("GET", "/system/ai/status", token)
    print(f"ai/status: {status} {payload}")
    assert status in (200, 502, 503), status
    if status == 200:
        assert "key" not in json.dumps(payload).lower(), "ключ не должен попадать в ответы"

    status, tasks = call("GET", "/study-tasks", token)
    assert status == 200, f"tasks: {status}"
    assert tasks, "нет учебных задач в БД"
    task = next((t for t in tasks if t.get("event_class_id")), tasks[0])
    print(f"task: {task['id']} status={task['status']} class={task.get('event_class_id')}")

    status, payload = call("POST", f"/study-tasks/{task['id']}/generate", token, {})
    print(f"generate: {status} {str(payload)[:160]}")
    assert status in (200, 422, 502, 503), status

    status, payload = call(
        "POST", f"/study-tasks/{task['id']}/caller-reply", token,
        {"question": "Здравствуйте, что случилось?", "turns": []},
    )
    print(f"caller-reply: {status} {str(payload)[:160]}")
    assert status in (200, 422, 502, 503), status

    status, payload = call("POST", f"/study-tasks/{task['id']}/reference-preview", token, {})
    print(f"reference-preview: {status} {str(payload)[:160]}")
    assert status in (200, 422, 502, 503), status

    status, payload = call("POST", f"/study-tasks/{task['id']}/validate-fields", token,
                           {"content": {"bad": "structure"}})
    print(f"validate-fields(bad): {status} {str(payload)[:160]}")
    assert status == 422, status

    # карточки: без тренировки ожидаем 404
    status, payload = call("POST", "/cards/00000000-0000-0000-0000-000000000000/caller-reply", token,
                           {"question": "test", "turns": []})
    print(f"card caller-reply (нет карточки): {status}")
    assert status == 404, status

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
