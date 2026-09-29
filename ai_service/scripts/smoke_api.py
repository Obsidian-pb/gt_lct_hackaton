"""Smoke-тест ИИ-микросервиса (backend_new не требуется).

Использование (микросервис уже запущен):
    python scripts/smoke_api.py [base_url] [token] [--live]

- base_url: по умолчанию http://127.0.0.1:8890;
- token: значение AI_SERVICE_TOKEN (по умолчанию из окружения);
- --live: дополнительно реальная генерация карточки и реплика заявителя
  (нужны ключ провайдера и квота; результат не сохраняется).

Без токена скрипт проверяет /health, 401 на защищённых операциях и
корректность контракта документации.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "http://127.0.0.1:8890"
ARGS = [a for a in sys.argv[1:] if a.startswith("--")]
TOKEN = next((a for a in sys.argv[1:] if not a.startswith("--") and "://" not in a), None) or os.environ.get("AI_SERVICE_TOKEN", "")
LIVE = "--live" in ARGS


def call(method: str, path: str, body: dict | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
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
    except OSError as exc:
        print(f"FAIL: сервер недоступен ({exc})")
        sys.exit(2)


def main() -> int:
    status, payload = call("GET", "/health")
    print(f"GET  /health: {status} {payload}")
    assert status == 200, "микросервис не запущен"

    status, _ = call("POST", "/api/v1/cards/validations", {"content": {"bad": True}})
    print(f"POST /cards/validations без токена: {status}")
    assert status == 401, "операция без токена должна давать 401"

    if not TOKEN:
        print("\nТокен не передан: защищённые операции не проверяются.")
        print("Передайте его аргументом или задайте AI_SERVICE_TOKEN (см. README).")
        print("SMOKE OK (базовая проверка)")
        return 0

    status, payload = call("GET", "/api/v1/metadata", token=TOKEN)
    print(f"GET  /metadata: {status}")
    assert status == 200 and "groups" in payload and "catalog" in payload, payload

    status, _ = call("POST", "/api/v1/cards/validations", {"content": {"bad": True}}, token=TOKEN)
    print(f"POST /cards/validations (bad): {status}")
    assert status == 422, "невалидный content должен давать 422"

    status, payload = call("POST", "/api/v1/ai/checks", {}, token=TOKEN)
    print(f"POST /ai/checks: {status} {str(payload)[:200]}")
    assert status in (200, 502, 503), status
    if status == 200:
        assert "key" not in json.dumps(payload).lower(), "ключ не должен попадать в ответы"

    if LIVE:
        status, payload = call("POST", "/api/v1/cards/generations",
                               {"topic": "пожар в жилом доме, улица Лесная 7, возможны люди внутри",
                                "total": 1, "index": 1}, token=TOKEN)
        print(f"POST /cards/generations (live): {status} {str(payload)[:200]}")
        assert status == 200, payload
        content = payload["content"]
        assert content["title"] and content["report"], "генерация вернула пустую карточку"

        scenario = {"version": 1, "phone_callback": "+7 (000) 123-45-67"}
        status, payload = call("POST", "/api/v1/cards/caller-replies",
                               {"content": content, "caller_scenario": scenario,
                                "question": "Назовите адрес происшествия", "turns": []}, token=TOKEN)
        print(f"POST /cards/caller-replies (live): {status} {str(payload)[:200]}")
        assert status == 200 and payload.get("reply"), payload
    else:
        print("--live не указан: реальная генерация ИИ пропущена.")

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())