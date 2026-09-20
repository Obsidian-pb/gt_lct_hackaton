"""Состояние комплекса: нагрузка на сервер, база, модель, резервные копии.

Администратор учебного комплекса работает только через браузер: доступа
к серверу, журналам контейнеров и командной строке у него нет. Поэтому всё,
по чему видно «жив ли комплекс», собирается здесь и показывается на одной
странице кабинета — иначе требование ТЗ «контролировать состояние всех
компонентов» выполнить нечем.

Сторонних библиотек модуль не требует намеренно. psutil пришлось бы собирать
под каждую платформу и обновлять ради трёх чисел, а берёт он их из тех же
файлов /proc и /sys/fs/cgroup, которые приложение читает здесь само.

Каждый показатель отдаётся в одном виде: `ok` — можно ли считать компонент
исправным (None, когда судить не по чему), `note` — объяснение человеческим
языком, остальные поля — числа для показа. Единый вид нужен, чтобы страница
раскрашивала блоки одинаково и не толковала каждый показатель по-своему.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Момент запуска процесса. Берётся при импорте модуля, а не из /proc/uptime:
# /proc/uptime — это время жизни машины, а администратору важно, не
# перезапускалось ли само приложение (падение и подъём контейнера видно
# именно по обнулению этого счётчика).
STARTED_AT = datetime.now(timezone.utc)

CGROUP = Path("/sys/fs/cgroup")

# Каталог резервных копий читается из окружения, а не из настроек приложения:
# это не настройка комплекса, а точка монтирования тома db-backups, заданная
# в docker-compose. Там, где том не смонтирован (разработка, тесты), каталога
# просто нет, и раздел честно сообщает, что сведений о копиях не получил.
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))

# Порог устаревания копии тот же, что у healthcheck контейнера backup: 25 часов
# при суточном графике. Держать здесь своё значение нельзя — страница и
# healthcheck разошлись бы в оценке одного и того же состояния.
BACKUP_MAX_AGE_HOURS = 25.0

# Как часто проверяется связь с языковой моделью и сколько ждём ответа.
# Проверка идёт фоном, а страница показывает последний известный результат:
# обращение к модели по сети занимает секунды, а страница обновляется у
# администратора постоянно — блокировать её ради этого нельзя.
LLM_PROBE_TTL_SECONDS = 60.0
LLM_PROBE_TIMEOUT_SECONDS = 3.0


def _read(path: Path) -> str | None:
    """Содержимое служебного файла ядра или None, если его нет.

    Отсутствие файла — обычное дело: набор файлов зависит от версии cgroup,
    от того, запущено ли приложение в контейнере, и от операционной системы
    (на рабочей машине разработчика /proc и /sys/fs/cgroup нет вовсе).
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    raw = _read(path)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _stat_value(path: Path, key: str) -> int | None:
    """Значение из файла вида «ключ число» в каждой строке (memory.stat, cpu.stat)."""
    raw = _read(path)
    if raw is None:
        return None
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == key:
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


# --- Нагрузка на сервер ------------------------------------------------------
#
# Все три показателя относятся к контейнеру приложения, а не к машине целиком,
# и в ответе это сказано полем `scope`. Разница существенная: сервер учебного
# комплекса общий с другими проектами, и «на машине занято 80 % памяти» ничего
# не говорит о том, близок ли к своему пределу сам комплекс.

_cpu_lock = threading.Lock()
# Предыдущий замер: (момент по монотонным часам, израсходованное время ЦП, с).
_cpu_previous: tuple[float, float] | None = None


def _cpu_seconds_used() -> float | None:
    """Процессорное время, израсходованное контейнером с его запуска."""
    usec = _stat_value(CGROUP / "cpu.stat", "usage_usec")  # cgroup v2
    if usec is not None:
        return usec / 1_000_000
    for name in ("cpuacct/cpuacct.usage", "cpu,cpuacct/cpuacct.usage"):  # cgroup v1
        nanoseconds = _read_int(CGROUP / name)
        if nanoseconds is not None:
            return nanoseconds / 1_000_000_000
    return None


def _cpu_limit_cores() -> float | None:
    """Сколько ядер разрешено контейнеру, или None, если ограничения нет."""
    raw = _read(CGROUP / "cpu.max")  # cgroup v2: «квота период» либо «max период»
    if raw:
        parts = raw.split()
        if parts and parts[0] != "max":
            period = int(parts[1]) if len(parts) > 1 else 100_000
            return int(parts[0]) / period if period else None
        return None
    quota = _read_int(CGROUP / "cpu/cpu.cfs_quota_us")  # cgroup v1
    period = _read_int(CGROUP / "cpu/cpu.cfs_period_us")
    if quota and quota > 0 and period:
        return quota / period
    return None


def _load_average() -> float | None:
    raw = _read(Path("/proc/loadavg"))
    if not raw:
        return None
    try:
        return float(raw.split()[0])
    except (IndexError, ValueError):
        return None


def _cpu() -> dict:
    """Загрузка процессора в процентах от того, что отведено контейнеру.

    Мгновенной загрузки процессора не существует: она считается по разнице
    израсходованного процессорного времени между двумя замерами. Замер
    сохраняется от показа к показу, поэтому первое открытие страницы числа
    не даёт, а последующие показывают среднее за интервал автообновления —
    это честнее, чем задержать ответ на секунду ради собственного замера.
    """
    global _cpu_previous

    limit = _cpu_limit_cores()
    average = _load_average()
    used = _cpu_seconds_used()
    if used is None:
        return {
            "percent": None,
            "limit_cores": limit,
            "load_average_1m": average,
            "scope": "контейнер приложения",
            "note": "Показатель доступен только при работе в контейнере Linux.",
        }

    now = time.monotonic()
    with _cpu_lock:
        previous = _cpu_previous
        # Замер не обновляется чаще раза в секунду: на коротком промежутке
        # разница процессорного времени состоит в основном из шума.
        if previous is None or now - previous[0] >= 1.0:
            _cpu_previous = (now, used)

    percent = None
    if previous is not None and now - previous[0] >= 0.2:
        cores = limit or os.cpu_count() or 1
        share = (used - previous[1]) / ((now - previous[0]) * cores)
        percent = round(max(0.0, min(share, 1.0)) * 100, 1)

    return {
        "percent": percent,
        "limit_cores": limit,
        "load_average_1m": average,
        "scope": "контейнер приложения",
        "note": (
            "Доля от отведённого комплексу процессорного времени."
            if percent is not None
            else "Показатель появится при следующем обновлении страницы."
        ),
    }


def _memory() -> dict:
    """Занятая память контейнера и его предел.

    Читается из cgroup, а не из /proc/meminfo, и это не придирка: внутри
    контейнера /proc/meminfo показывает память всей машины, а не предел
    контейнера (`mem_limit: 768m` в docker-compose.prod.yml). По meminfo
    комплекс, упирающийся в свой предел и убиваемый ядром за перерасход,
    выглядел бы как занявший десятую долю памяти сервера — то есть ровно в
    той ситуации, ради которой показатель и заведён, он бы и промолчал.

    Из занятого вычитается файловый кеш (inactive_file): ядро держит в нём
    прочитанные файлы и отдаёт их обратно под давлением, поэтому без вычета
    показатель почти всегда упирался бы в предел. Так же считает docker stats.
    """
    current = _read_int(CGROUP / "memory.current")  # cgroup v2
    if current is not None:
        raw_limit = (_read(CGROUP / "memory.max") or "max").strip()
        limit = None if raw_limit == "max" else int(raw_limit)
        cache = _stat_value(CGROUP / "memory.stat", "inactive_file") or 0
        used, scope = current - cache, "контейнер приложения"
    else:
        current = _read_int(CGROUP / "memory/memory.usage_in_bytes")  # cgroup v1
        if current is not None:
            raw_v1 = _read_int(CGROUP / "memory/memory.limit_in_bytes")
            # «Предела нет» в cgroup v1 выглядит как заведомо недостижимое
            # число вроде 9223372036854771712, а не как отдельное значение.
            limit = raw_v1 if raw_v1 and raw_v1 < 2**60 else None
            cache = _stat_value(CGROUP / "memory/memory.stat", "total_inactive_file") or 0
            used, scope = current - cache, "контейнер приложения"
        else:
            total = _stat_value(Path("/proc/meminfo"), "MemTotal:")
            available = _stat_value(Path("/proc/meminfo"), "MemAvailable:")
            if total is None or available is None:
                return {
                    "used_bytes": None,
                    "limit_bytes": None,
                    "percent": None,
                    "scope": "контейнер приложения",
                    "note": "Показатель доступен только при работе в контейнере Linux.",
                }
            # Единицы в /proc/meminfo — килобайты. Предела контейнера здесь
            # нет, поэтому и сказано прямо: это память сервера целиком.
            used, limit, scope = (total - available) * 1024, total * 1024, "сервер целиком"

    if limit is None:
        # Контейнер без предела памяти упирается в память машины — её и берём
        # за потолок, иначе показывать проценты не от чего.
        host_total = _stat_value(Path("/proc/meminfo"), "MemTotal:")
        limit = host_total * 1024 if host_total else None
        scope = "контейнер приложения, предел не задан"

    percent = round(used / limit * 100, 1) if limit else None
    return {
        "used_bytes": max(used, 0),
        "limit_bytes": limit,
        "percent": percent,
        "scope": scope,
        "note": "Занято без учёта файлового кеша — так же считает сам Docker.",
    }


def _disk() -> dict:
    """Место на диске, на котором работает комплекс.

    Отдельного тома у приложения нет, поэтому берётся корневая файловая
    система контейнера: физически это диск сервера, и переполняется он общий
    — вместе с базой, копиями и загруженными учебными материалами.
    """
    try:
        stat = os.statvfs("/")
    except OSError:
        return {
            "used_bytes": None,
            "total_bytes": None,
            "percent": None,
            "note": "Сведения о диске недоступны.",
        }
    total = stat.f_blocks * stat.f_frsize
    # f_bavail, а не f_bfree: часть места зарезервирована за суперпользователем
    # и приложению недоступна, показывать её как свободную — вводить в
    # заблуждение.
    free = stat.f_bavail * stat.f_frsize
    used = total - free
    return {
        "used_bytes": used,
        "total_bytes": total,
        "percent": round(used / total * 100, 1) if total else None,
        "note": "Диск сервера, общий для базы, копий и учебных материалов.",
    }


def load() -> dict:
    """Нагрузка на сервер: процессор, оперативная память, диск."""
    return {"cpu": _cpu(), "memory": _memory(), "disk": _disk()}


# --- База данных -------------------------------------------------------------


def database(db: Session) -> dict:
    """Отвечает ли база и за сколько.

    Время отклика меряется на самом дешёвом запросе: нужен признак живости и
    порядок величины задержки, а не замер производительности. Полностью
    отказавшую базу этот показатель, впрочем, покажет редко — без базы не
    пройдёт и вход администратора в кабинет; ценность его в другом: по
    времени отклика, выросшему с привычных единиц миллисекунд до сотен,
    видно, что комплекс начал тормозить, ещё до того, как это заметят
    на занятии.
    """
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — любая ошибка здесь означает отказ базы
        logger.warning("Проверка базы данных не удалась: %s", exc)
        return {
            "ok": False,
            "response_ms": None,
            "note": "База данных не отвечает на запросы.",
        }
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    return {
        "ok": True,
        "response_ms": elapsed,
        "note": "База отвечает, обращения проходят.",
    }


# --- Языковая модель ---------------------------------------------------------

_llm_lock = threading.Lock()
_llm_result: dict | None = None
_llm_checked_monotonic = 0.0
_llm_probing = False


def _probe_llm() -> dict:
    """Проверка связи с провайдером языковой модели. Выполняется фоном."""
    settings = get_settings()
    if settings.llm_provider == "gigachat":
        # Сам сервис не опрашивается: любое обращение к нему тратит лимит
        # запросов и требует обмена ключа на токен. Для страницы состояния
        # достаточно знать, что до узла авторизации есть сеть, — недоступность
        # именно сети и есть самая частая причина отказа в закрытом контуре.
        from app.llm.gigachat import OAUTH_URL

        parsed = urlparse(OAUTH_URL)
        host, port = parsed.hostname or "", parsed.port or 443
        try:
            with socket.create_connection((host, port), LLM_PROBE_TIMEOUT_SECONDS):
                pass
        except OSError as exc:
            return {"ok": False, "note": f"Нет связи с узлом {host}: {exc}"}
        return {"ok": True, "note": f"Узел авторизации {host} доступен."}

    url = settings.llm_base_url.rstrip("/") + "/models"
    key = settings.llm_api_key
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        response = httpx.get(url, headers=headers, timeout=LLM_PROBE_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        return {"ok": False, "note": f"Сервис модели не отвечает: {exc}"}
    if response.status_code in (401, 403):
        return {"ok": False, "note": "Сервис модели отвечает, но ключ доступа не принят."}
    if response.status_code >= 500:
        return {
            "ok": False,
            "note": f"Сервис модели отвечает ошибкой {response.status_code}.",
        }
    return {"ok": True, "note": "Сервис модели отвечает."}


def _refresh_llm() -> None:
    global _llm_result, _llm_checked_monotonic, _llm_probing
    try:
        result = _probe_llm()
    except Exception as exc:  # noqa: BLE001 — проверка не вправе ронять поток
        logger.warning("Проверка связи с языковой моделью не удалась: %s", exc)
        result = {"ok": None, "note": "Проверить связь с моделью не удалось."}
    with _llm_lock:
        _llm_result = {**result, "checked_at": datetime.now(timezone.utc)}
        _llm_checked_monotonic = time.monotonic()
        _llm_probing = False


def llm() -> dict:
    """Какой провайдер включён и отвечает ли он.

    Страница обновляется каждые несколько секунд, а проверка связи занимает
    до трёх секунд, поэтому показывается последний известный результат, а
    новая проверка запускается отдельным потоком не чаще раза в минуту.
    Администратор получает ответ мгновенно, а сведения отстают на минуту —
    для «жив ли комплекс» этого достаточно.
    """
    global _llm_probing

    settings = get_settings()
    common = {"provider": settings.llm_provider, "model": settings.llm_model}
    if settings.llm_provider == "stub":
        return {
            **common,
            "model": "—",
            "ok": True,
            "checked_at": None,
            "note": "Включена встроенная заглушка: комплекс работает без внешней модели.",
        }

    with _llm_lock:
        result = _llm_result
        stale = time.monotonic() - _llm_checked_monotonic > LLM_PROBE_TTL_SECONDS
        if (result is None or stale) and not _llm_probing:
            _llm_probing = True
            threading.Thread(target=_refresh_llm, daemon=True).start()

    if result is None:
        return {
            **common,
            "ok": None,
            "checked_at": None,
            "note": "Связь с моделью проверяется, результат появится при следующем обновлении.",
        }
    return {**common, **result}


# --- Резервные копии ---------------------------------------------------------


def backups() -> dict:
    """Свежесть резервных копий базы по отметкам, которые оставляет ops/backup.

    Копии снимает отдельный контейнер в свой том, и приложение о ходе
    копирования ничего не знает — а требование ТЗ наблюдать за копированием
    остаётся. Поэтому том db-backups смонтирован приложению только на чтение,
    и разбираются те же отметки, по которым проверяет себя сам контейнер
    копирования: last-success, last-failure и latest.dump. Своей проверки
    копий приложение не заводит: два независимых мнения о том, снята ли
    копия, хуже одного.
    """
    if not BACKUP_DIR.is_dir():
        return {
            "ok": None,
            "last_success_at": None,
            "age_hours": None,
            "count": None,
            "latest_size_bytes": None,
            "last_failure": None,
            "note": (
                "Каталог резервных копий комплексу не виден: копирование "
                "либо не настроено, либо том с копиями не подключён."
            ),
        }

    failure = (_read(BACKUP_DIR / "last-failure") or "").strip() or None
    # Считаются только готовые копии: имена оборванных начинаются с точки,
    # а latest.dump — ссылка на последнюю из этих же файлов.
    copies = sorted(BACKUP_DIR.glob("*Z.dump"))
    latest = BACKUP_DIR / "latest.dump"
    size = latest.stat().st_size if latest.exists() else None

    success = (_read(BACKUP_DIR / "last-success") or "").split()
    if not success:
        return {
            "ok": False,
            "last_success_at": None,
            "age_hours": None,
            "count": len(copies),
            "latest_size_bytes": size,
            "last_failure": failure,
            "note": "Успешных копий ещё не было.",
        }

    try:
        at = datetime.fromtimestamp(int(success[0]), timezone.utc)
    except (ValueError, OverflowError, OSError):
        return {
            "ok": False,
            "last_success_at": None,
            "age_hours": None,
            "count": len(copies),
            "latest_size_bytes": size,
            "last_failure": failure,
            "note": "Отметка о последней копии испорчена.",
        }

    age = (datetime.now(timezone.utc) - at).total_seconds() / 3600
    fresh = age <= BACKUP_MAX_AGE_HOURS and size is not None
    if size is None:
        note = "Отметка об успехе есть, а файла последней копии нет."
    elif fresh:
        note = "Копии снимаются по графику, последняя пригодна к восстановлению."
    else:
        note = (
            f"Последняя копия снята более {BACKUP_MAX_AGE_HOURS:.0f} ч назад — "
            "копирование остановилось."
        )
    return {
        "ok": fresh,
        "last_success_at": at,
        "age_hours": round(age, 1),
        "count": len(copies),
        "latest_size_bytes": size,
        "last_failure": failure,
        "note": note,
    }


def uptime_seconds() -> float:
    """Сколько приложение работает без перезапуска."""
    return round((datetime.now(timezone.utc) - STARTED_AT).total_seconds(), 1)
