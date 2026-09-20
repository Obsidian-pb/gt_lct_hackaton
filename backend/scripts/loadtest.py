"""Проверка показателей производительности из технического задания.

Техническое задание задаёт четыре числа, и до сих пор ни одно из них
не было измерено: заявлять соответствие, не проверив, нельзя.

    отклик интерфейса        не более 2 с при нагрузке до 100 пользователей
    одновременные сессии     не менее 20 (вызовов/карточек)
    запись в базу            не менее 100 операций в секунду
    аналитический отчёт      не более 30 с

Меряется время ответа сервера, а не отрисовки в браузере: оно и есть то,
чем распоряжается наша часть решения. Отдельно считается девяносто пятый
процентиль, а не только среднее: норматив нарушает не средний пользователь,
а тот, кому не повезло.

Сторонние средства нагрузки не нужны — httpx уже есть в зависимостях.

Запуск (приложение должно работать):
    python scripts/loadtest.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Нормативы технического задания.
RESPONSE_LIMIT_SECONDS = 2.0
CONCURRENT_SESSIONS = 20
WRITES_PER_SECOND = 100
REPORT_LIMIT_SECONDS = 30.0


def trust_env_for(base_url: str) -> bool:
    """К локальному адресу нельзя ходить через HTTP_PROXY из окружения.

    Прокси не знает про петлевой интерфейс и частные сети, запрос к нему
    уходит в никуда. Та же оговорка сделана в провайдере языковой модели —
    и по той же причине.
    """
    host = urlparse(base_url).hostname or ""
    if host in {"localhost", "host.docker.internal"}:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (address.is_loopback or address.is_private)


@dataclass
class Measurement:
    name: str
    limit: str
    result: str
    passed: bool
    detail: str = ""


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    index = min(int(len(ordered) * share), len(ordered) - 1)
    return ordered[index]


async def login(client: httpx.AsyncClient, login_name: str, password: str | None) -> str:
    # На учебном стенде пароль задаётся DEMO_PASSWORD и одинаков у всех,
    # а в разработке совпадает с логином — отсюда значение по умолчанию.
    password = password or login_name
    response = await client.post(
        "/api/auth/token", data={"username": login_name, "password": password}
    )
    response.raise_for_status()
    return response.json()["access_token"]


async def timed(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> tuple[float, int]:
    started = time.perf_counter()
    response = await client.request(method, path, **kwargs)
    return time.perf_counter() - started, response.status_code


async def measure_reading(base_url: str, token: str, users: int) -> Measurement:
    """Отклик на чтение при заданном числе одновременных пользователей."""
    headers = {"Authorization": f"Bearer {token}"}
    # Страница ленты карточек — то, что обучающийся открывает чаще всего.
    paths = ["/api/attempts/my", "/api/operator/calls/my", "/api/student/progress"]

    async def one(client: httpx.AsyncClient, number: int) -> float:
        elapsed, code = await timed(client, "GET", paths[number % len(paths)], headers=headers)
        return elapsed if code == 200 else float("inf")

    limits = httpx.Limits(max_connections=users, max_keepalive_connections=users)
    async with httpx.AsyncClient(
        base_url=base_url, limits=limits, timeout=60.0, trust_env=trust_env_for(base_url)
    ) as client:
        times = await asyncio.gather(*(one(client, n) for n in range(users)))

    failed = sum(1 for t in times if t == float("inf"))
    ok = [t for t in times if t != float("inf")]
    p95 = percentile(ok, 0.95) if ok else float("inf")
    return Measurement(
        name=f"Отклик при {users} одновременных пользователях",
        limit=f"не более {RESPONSE_LIMIT_SECONDS:.0f} с",
        result=f"95-й процентиль {p95:.2f} с, среднее {statistics.mean(ok):.2f} с",
        passed=bool(ok) and p95 <= RESPONSE_LIMIT_SECONDS and not failed,
        detail=f"неуспешных ответов: {failed}" if failed else "",
    )


async def measure_sessions(base_url: str, token: str, count: int) -> Measurement:
    """Одновременная работа с карточками: у каждой сессии свой поток обращений."""
    headers = {"Authorization": f"Bearer {token}"}

    async def session(client: httpx.AsyncClient) -> list[float]:
        times = []
        # Один цикл работы: посмотреть ленту, открыть карточку, обновить таймер.
        for path in ("/api/attempts/my", "/api/operator/calls/my", "/api/attempts/my"):
            elapsed, code = await timed(client, "GET", path, headers=headers)
            times.append(elapsed if code == 200 else float("inf"))
        return times

    limits = httpx.Limits(max_connections=count * 2, max_keepalive_connections=count * 2)
    started = time.perf_counter()
    async with httpx.AsyncClient(
        base_url=base_url, limits=limits, timeout=60.0, trust_env=trust_env_for(base_url)
    ) as client:
        batches = await asyncio.gather(*(session(client) for _ in range(count)))
    total = time.perf_counter() - started

    times = [t for batch in batches for t in batch]
    ok = [t for t in times if t != float("inf")]
    p95 = percentile(ok, 0.95) if ok else float("inf")
    return Measurement(
        name=f"{count} одновременных сессий",
        limit=f"не менее {CONCURRENT_SESSIONS}, отклик не более {RESPONSE_LIMIT_SECONDS:.0f} с",
        result=f"{len(ok)} из {len(times)} обращений, 95-й процентиль {p95:.2f} с, всего {total:.1f} с",
        passed=len(ok) == len(times) and p95 <= RESPONSE_LIMIT_SECONDS,
    )


async def measure_writes(base_url: str, token: str, operations: int) -> Measurement:
    """Скорость записи: проставление статусов — самая частая операция записи."""
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0, trust_env=trust_env_for(base_url)) as client:
        cards = (await client.get("/api/attempts/my", headers=headers)).json()
        open_cards = [c for c in cards if not c["finished"]]
        if not open_cards:
            return Measurement(
                name="Скорость записи в базу",
                limit=f"не менее {WRITES_PER_SECOND} операций в секунду",
                result="нет незавершённых карточек",
                passed=False,
                detail="выполните scripts/reissue.py и повторите",
            )

        # Открытие карточки — операция записи, доступная многократно:
        # повторный вызов обновляет попытку, не меняя её состояние необратимо.
        target = open_cards[0]["attempt_id"]
        limits = httpx.Limits(max_connections=32, max_keepalive_connections=32)

    async def one(client: httpx.AsyncClient) -> bool:
        _, code = await timed(client, "POST", f"/api/attempts/{target}/open", headers=headers)
        return code == 200

    async with httpx.AsyncClient(
        base_url=base_url, limits=limits, timeout=60.0, trust_env=trust_env_for(base_url)
    ) as client:
        started = time.perf_counter()
        results = await asyncio.gather(*(one(client) for _ in range(operations)))
        total = time.perf_counter() - started

    rate = sum(results) / total if total else 0.0
    return Measurement(
        name="Скорость записи в базу",
        limit=f"не менее {WRITES_PER_SECOND} операций в секунду",
        result=f"{rate:.0f} операций в секунду ({sum(results)} за {total:.2f} с)",
        passed=rate >= WRITES_PER_SECOND,
    )


async def measure_report(base_url: str, password: str | None) -> Measurement:
    """Формирование аналитического отчёта преподавателя."""
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0, trust_env=trust_env_for(base_url)) as client:
        token = await login(client, "teacher", password)
        headers = {"Authorization": f"Bearer {token}"}
        sessions = (await client.get("/api/teacher/sessions", headers=headers)).json()
        if not sessions:
            return Measurement(
                name="Формирование отчёта",
                limit=f"не более {REPORT_LIMIT_SECONDS:.0f} с",
                result="занятий нет",
                passed=False,
            )
        # Худший случай — занятие, по которому больше всего работ: отчёт
        # считается по попыткам, а не по сценариям, и на занятии без попыток
        # замер ничего не значит.
        heaviest = None
        most = -1
        for item in sessions:
            report = (
                await client.get(f"/api/teacher/sessions/{item['id']}/report", headers=headers)
            ).json()
            if report.get("total_attempts", 0) > most:
                most, heaviest = report["total_attempts"], item
        if heaviest is None or most <= 0:
            return Measurement(
                name="Формирование аналитического отчёта",
                limit=f"не более {REPORT_LIMIT_SECONDS:.0f} с",
                result="ни по одному занятию нет работ — замерять нечего",
                passed=False,
            )
        times = []
        for _ in range(3):
            elapsed, code = await timed(
                client, "GET", f"/api/teacher/sessions/{heaviest['id']}/report", headers=headers
            )
            times.append(elapsed if code == 200 else float("inf"))

    worst = max(times)
    return Measurement(
        name="Формирование аналитического отчёта",
        limit=f"не более {REPORT_LIMIT_SECONDS:.0f} с",
        result=f"худший из трёх прогонов {worst:.2f} с (занятие из {most} работ)",
        passed=worst <= REPORT_LIMIT_SECONDS,
    )


async def main(base_url: str, password: str | None, users: int) -> int:
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0, trust_env=trust_env_for(base_url)) as client:
        health = await client.get("/api/health")
        if health.status_code != 200:
            print(f"Приложение не отвечает на {base_url}", file=sys.stderr)
            return 1
        token = await login(client, "student", password)

    print(f"Замер на {base_url}\n")
    results = [
        await measure_reading(base_url, token, users),
        await measure_sessions(base_url, token, CONCURRENT_SESSIONS),
        await measure_writes(base_url, token, 200),
        await measure_report(base_url, password),
    ]

    width = max(len(r.name) for r in results)
    for r in results:
        mark = "да " if r.passed else "НЕТ"
        print(f"  [{mark}] {r.name:<{width}}  {r.limit}")
        print(f"        {r.result}")
        if r.detail:
            print(f"        {r.detail}")
    failed = [r for r in results if not r.passed]
    print(f"\nНорматив выдержан: {len(results) - len(failed)} из {len(results)}.")
    return 1 if failed else 0


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Проверка нормативов производительности из ТЗ")
    cli.add_argument("--base-url", default="http://localhost:8000")
    cli.add_argument(
        "--password",
        default=None,
        help="пароль учебных записей; по умолчанию совпадает с логином",
    )
    cli.add_argument("--users", type=int, default=100, help="одновременных пользователей")
    args = cli.parse_args()
    raise SystemExit(asyncio.run(main(args.base_url, args.password, args.users)))
