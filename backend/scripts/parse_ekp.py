"""Разбор classificator.xlsx (ЕКП) в ekp.json.

Структура исходника: три строки заголовка, дальше строки-правила, перемежающиеся
строками-разделителями групп происшествий.

Колонки 0-11 описывают само правило, 12 — главную службу, 13+ — список оповещения.
У части служб несколько подколонок: какая из них применяется, зависит от флагов
опросной карты (пострадавшие, нет доступа, газификация и т.п.).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import openpyxl

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SRC = BACKEND_DIR.parent / "classificator.xlsx"
DEFAULT_DST = BACKEND_DIR / "data" / "ekp.json"

COL_G, COL_P1, COL_P2, COL_P3 = 0, 1, 2, 3
COL_NUMBER, COL_SUBGROUP = 4, 5
COL_SIGN1, COL_SIGN2, COL_SIGN3 = 6, 7, 8
COL_HINTS, COL_TYPE, COL_TYPE_EKP35, COL_MAIN_SERVICE = 9, 10, 11, 12
FIRST_SERVICE_COL = 13

# Подколонки служб, зависящие от флагов опросной карты. Ключ — подпись в шапке
# (после нормализации), значение — флаги, при которых подколонка применяется.
# None означает подколонку по умолчанию: когда ни один из флагов службы не взведён.
VARIANT_FLAGS = {
    "служба 101 (признак нд - нет доступа не выбран)": None,
    "служба 101 (выбран признак нд - нет доступа)": ["нет_доступа"],
    "одс псц (другие признаки не выбраны)": None,
    "одс псц (выбран признак ул - угроза людям)": ["угроза_людям"],
    "одс псц (выбран признак пп - пострадавшие погибшие)": ["пострадавшие"],
    "одс псц (выбран признак нд - нет доступа)": ["нет_доступа"],
    "признак правонарушение или пострадавшие не выбран": None,
    "выбран признак правонарушение": ["правонарушение"],
    "выбран признак пострадавшие": ["пострадавшие"],
    "классификатор смп (признак пострадавшие не выбран)": None,
    "классификатор смп (выбран признак пострадавшие)": ["пострадавшие"],
    "классификатор смп (выбран признак пострадавшие не на месте)": ["пострадавшие_не_на_месте"],
    "признак не выбран": None,
    "признаки не выбраны": None,
    "газификация": ["газификация"],
    "угроза людям": ["угроза_людям"],
    "пострадавшие/погибшие": ["пострадавшие"],
    "постр / погибшие": ["пострадавшие"],
    "мед. помощь": ["мед_помощь"],
    "треб. эвакуация": ["эвакуация"],
    ">5 чел / од": ["массовое"],
    "перекрытие движение": ["перекрытие_движения"],
    "тоннель": ["тоннель"],
    "пеш": ["пешеходный_переход"],
    "ав": ["автомобильный"],
    "стройка": ["стройка"],
    "объект из перечня": ["объект_из_перечня"],
    "реагирование всегда": None,
    "на объектах связи": ["объект_связи"],
    "пожары": ["пожар"],
    "москва": None,
}

# Подколонки, которые задают не условие, а канал доставки или подразделение
# внутри службы. Применяются всегда, когда в ячейке есть значение.
CHANNEL_VARIANTS = {
    "арм-112",
    "дежурная служба арм-112",
    "интеграция",
    "мгпсс",
    "мкп, аналитика (старый крим)",
    "(куб)",
    "события по полигонам",
}


def norm(value):
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()
    return text or None


def service_name(raw):
    """Приводит заголовок колонки к названию службы.

    В таблице колонки названы «Классификатор МВД», «Классификатор СМП» —
    это про классификатор соответствующей службы, а не про её имя. В списке
    оповещения такие подписи выглядят нелепо, поэтому приставку снимаем.
    """
    text = norm(raw)
    if text and text.startswith("Классификатор "):
        text = text[len("Классификатор ") :].strip()
    return text or None


def read_services(header_rows):
    """Собирает описание колонок служб из трёхстрочной шапки.

    Имя службы в первой строке объединено на несколько колонок, поэтому
    протягиваем последнее непустое значение вправо.
    """
    row1, row2, row3 = header_rows
    services = []
    current_name = None
    for col in range(FIRST_SERVICE_COL, len(row1)):
        name = service_name(row1[col]) if col < len(row1) else None
        if name:
            current_name = name
        if not current_name:
            continue
        label = norm(row3[col] if col < len(row3) else None) or norm(
            row2[col] if col < len(row2) else None
        )
        # Подпись совпадает с именем службы — это не условие, а сама колонка.
        variant = None if label == current_name else label
        key = (variant or "").lower()
        if not variant:
            kind, flags = "plain", None
        elif key in CHANNEL_VARIANTS:
            kind, flags = "channel", None
        else:
            kind, flags = "flag", VARIANT_FLAGS.get(key, "UNKNOWN")
        services.append(
            {"col": col, "service": current_name, "variant": variant, "kind": kind, "flags": flags}
        )
    return services


def parse(src: Path = DEFAULT_SRC, dst: Path = DEFAULT_DST):
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    services = read_services(rows[:3])

    unknown = sorted({s["variant"] for s in services if s["flags"] == "UNKNOWN"})

    if unknown:
        print("Неизвестные подколонки (нужно дополнить VARIANT_FLAGS):", file=sys.stderr)
        for item in unknown:
            print("  ", item, file=sys.stderr)

    rules, groups, group = [], [], None
    for row in rows[3:]:
        number = row[COL_NUMBER]
        if not isinstance(number, (int, float)):
            continue
        if number < 100:
            group = norm(row[COL_SUBGROUP])
            if group:
                groups.append(group)
            continue
        if group is None:
            continue

        notifications = []
        for svc in services:
            value = norm(row[svc["col"]]) if svc["col"] < len(row) else None
            if not value:
                continue
            flags = svc["flags"]
            notifications.append(
                {
                    "service": svc["service"],
                    "variant": svc["variant"],
                    "variant_kind": svc["kind"],
                    "requires_flags": flags if isinstance(flags, list) else [],
                    "is_default_variant": flags is None,
                    "incident_type_in_service": value,
                }
            )

        rules.append(
            {
                "number": int(number),
                "group": group,
                "subgroup": norm(row[COL_SUBGROUP]),
                "path": [row[COL_G], row[COL_P1], row[COL_P2], row[COL_P3]],
                "signs": [norm(row[COL_SIGN1]), norm(row[COL_SIGN2]), norm(row[COL_SIGN3])],
                "hints": norm(row[COL_HINTS]),
                "incident_type": norm(row[COL_TYPE]),
                "incident_type_ekp35": norm(row[COL_TYPE_EKP35]),
                "main_service": norm(row[COL_MAIN_SERVICE]),
                "notifications": notifications,
            }
        )

    payload = {
        "source": src.name,
        "groups": groups,
        "services": sorted({s["service"] for s in services}),
        "rules": rules,
    }
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"правил: {len(rules)}, групп: {len(groups)}, служб: {len(payload['services'])}")
    print(f"записано: {dst} ({dst.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Разбор классификатора ЕКП в ekp.json")
    cli.add_argument("--src", type=Path, default=DEFAULT_SRC, help="путь к classificator.xlsx")
    cli.add_argument("--dst", type=Path, default=DEFAULT_DST, help="куда записать ekp.json")
    args = cli.parse_args()
    parse(args.src, args.dst)
