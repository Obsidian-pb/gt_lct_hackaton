"""Разбор classificator.xlsx (ЕКП) в ekp.json.

Сам разбор живёт в `app/services/ekp_import.py`: им же пользуется загрузка
новой редакции классификатора администратором. Скрипт остаётся точкой входа
для сборки образа — там нужен готовый файл поставки `data/ekp.json`.
"""

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.services.ekp_import import ParseError, parse_workbook  # noqa: E402

DEFAULT_SRC = BACKEND_DIR.parent / "classificator.xlsx"
DEFAULT_DST = BACKEND_DIR / "data" / "ekp.json"


def parse(src: Path = DEFAULT_SRC, dst: Path = DEFAULT_DST):
    try:
        result = parse_workbook(src.read_bytes(), source=src.name)
    except ParseError as exc:
        sys.exit(f"ошибка: {exc}")

    if result.unknown_variants:
        print("Неизвестные подколонки (нужно дополнить VARIANT_FLAGS):", file=sys.stderr)
        for item in result.unknown_variants:
            print("  ", item, file=sys.stderr)

    payload = result.payload
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(
        f"правил: {len(payload['rules'])}, групп: {len(payload['groups'])}, "
        f"служб: {len(payload['services'])}"
    )
    print(f"записано: {dst} ({dst.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Разбор классификатора ЕКП в ekp.json")
    cli.add_argument("--src", type=Path, default=DEFAULT_SRC, help="путь к classificator.xlsx")
    cli.add_argument("--dst", type=Path, default=DEFAULT_DST, help="куда записать ekp.json")
    args = cli.parse_args()
    parse(args.src, args.dst)
