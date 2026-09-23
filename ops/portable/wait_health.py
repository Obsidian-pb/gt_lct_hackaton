"""Ожидание готовности сервера переносного комплекта.

Вызывается из start.cmd: `python wait_health.py <порт> <секунд>`. Отдельный
файл, а не строка в `-c`: cmd не переносит многострочные аргументы.
"""

import sys
import time
import urllib.request

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
budget = float(sys.argv[2]) if len(sys.argv) > 2 else 90
url = f"http://127.0.0.1:{port}/api/health"
deadline = time.time() + budget

while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=3):
            sys.exit(0)
    except Exception:  # noqa: BLE001 — до готовности любая ошибка означает «ещё не поднялся»
        time.sleep(1)
sys.exit(1)
