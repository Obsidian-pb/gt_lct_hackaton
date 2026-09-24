"""Резервная копия базы переносного комплекта.

Повторяет ops/backup/backup.sh для Windows: тот же формат архива, те же
имена файлов и те же отметки last-success / last-failure — раздел
«Состояние» разбирает их одинаково и в контейнере, и здесь. Своей логики
проверки копий у приложения нет, и второй заводить не надо.

Вызывается из start.cmd перед обновлением схемы и из stop.cmd перед
остановкой базы: копия «до миграции» и копия «на конец работы» — два
момента, когда её потом действительно ищут.

    python backup.py <pgsql\\bin> <порт> <каталог копий> [сколько хранить]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DATABASE = "trainer"
USER = "trainer"


def main() -> int:
    pg_bin = Path(sys.argv[1])
    port = sys.argv[2]
    backup_dir = Path(sys.argv[3])
    keep = int(sys.argv[4]) if len(sys.argv) > 4 else 14
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{DATABASE}-{stamp}.dump"
    # Под временным именем, переименование — только после проверки:
    # оборванный дамп не должен выглядеть готовой копией.
    partial = backup_dir / f".partial-{stamp}.dump"

    def fail(message: str) -> int:
        partial.unlink(missing_ok=True)
        (backup_dir / "last-failure").write_text(
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {message}\n",
            encoding="utf-8",
        )
        print(f"[backup] ОШИБКА: {message}")
        return 1

    common = ["-h", "127.0.0.1", "-p", port, "-U", USER]
    dump = subprocess.run(
        [str(pg_bin / "pg_dump.exe"), *common, "--format=custom", "--compress=6",
         f"--file={partial}", DATABASE],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if dump.returncode != 0:
        return fail("pg_dump завершился с ошибкой: " + dump.stderr.strip()[-300:])

    listing = subprocess.run(
        [str(pg_bin / "pg_restore.exe"), "--list", str(partial)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if listing.returncode != 0:
        return fail("архив не читается pg_restore — копия непригодна")
    entries = sum(1 for line in listing.stdout.splitlines() if line and not line.startswith(";"))
    if entries < 1:
        return fail("архив читается, но не содержит объектов")

    partial.replace(target)
    # Символических ссылок на Windows без прав нет — latest.dump копируется.
    shutil.copyfile(target, backup_dir / "latest.dump")
    (backup_dir / "last-success").write_text(f"{int(time.time())} {stamp}\n", encoding="utf-8")

    copies = sorted(backup_dir.glob("*Z.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in copies[keep:]:
        old.unlink(missing_ok=True)
        print(f"[backup] удалена устаревшая копия {old.name}")

    print(f"[backup] готово: {target.name}, {target.stat().st_size // 1024} КБ, объектов: {entries}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
