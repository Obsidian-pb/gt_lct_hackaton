"""Разбор исходного xlsx Единого классификатора происшествий.

Один и тот же разбор обслуживает два пути: сборку образа, где скрипт
`scripts/parse_ekp.py` пишет файл поставки `data/ekp.json`, и загрузку
новой редакции администратором из интерфейса. Держать две реализации
значило бы рано или поздно получить две разные трактовки одного файла,
а классификатор — источник истины для эталона.

Структура исходника: три строки заголовка, дальше строки-правила,
перемежающиеся строками-разделителями групп происшествий.

Колонки 0-11 описывают само правило, 12 — главную службу, 13+ — список
оповещения. У части служб несколько подколонок: какая из них применяется,
зависит от флагов опросной карты (пострадавшие, нет доступа, газификация
и т.п.).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import openpyxl

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


class ParseError(ValueError):
    """Файл не удалось прочитать как классификатор.

    Отдельный класс, чтобы слой API отличал негодный файл (ответ 422
    с объяснением) от сбоя самого комплекса (ответ 500 и запись в отчёт
    о сбоях).
    """


@dataclass
class ParseResult:
    payload: dict
    # Подписи подколонок, которых разбор не знает. Новая редакция может
    # завести новый признак — такой столбец не применяется ни при каких
    # флагах, и администратор должен об этом узнать, а не догадываться
    # по расхождению списков оповещения.
    unknown_variants: list[str] = field(default_factory=list)

    @property
    def rule_count(self) -> int:
        return len(self.payload["rules"])


def norm(value):
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()
    return text or None


def cell(row: tuple, index: int):
    """Ячейка по номеру колонки; за правым краем строки — пусто.

    В режиме чтения openpyxl отдаёт строки разной длины: хвост из пустых
    ячеек он отбрасывает, и короткая строка-разделитель роняла бы разбор.
    """
    return row[index] if index < len(row) else None


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


def parse_rows(rows: list[tuple], source: str) -> ParseResult:
    """Разбирает строки листа в словарь того же вида, что и `data/ekp.json`."""
    if len(rows) < 3:
        raise ParseError("В файле нет трёхстрочной шапки классификатора")
    services = read_services(rows[:3])
    if not services:
        raise ParseError(
            "В шапке не найдено ни одной службы: колонки списка оповещения "
            "должны начинаться с четырнадцатой"
        )
    unknown = sorted({s["variant"] for s in services if s["flags"] == "UNKNOWN"})

    rules, groups, group = [], [], None
    for row in rows[3:]:
        number = cell(row, COL_NUMBER)
        if not isinstance(number, (int, float)):
            continue
        if number < 100:
            group = norm(cell(row, COL_SUBGROUP))
            if group:
                groups.append(group)
            continue
        if group is None:
            continue

        notifications = []
        for svc in services:
            value = norm(cell(row, svc["col"]))
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
                "subgroup": norm(cell(row, COL_SUBGROUP)),
                "path": [cell(row, c) for c in (COL_G, COL_P1, COL_P2, COL_P3)],
                "signs": [norm(cell(row, c)) for c in (COL_SIGN1, COL_SIGN2, COL_SIGN3)],
                "hints": norm(cell(row, COL_HINTS)),
                "incident_type": norm(cell(row, COL_TYPE)),
                "incident_type_ekp35": norm(cell(row, COL_TYPE_EKP35)),
                "main_service": norm(cell(row, COL_MAIN_SERVICE)),
                "notifications": notifications,
            }
        )

    if not rules:
        raise ParseError(
            "В файле не найдено ни одного правила: это не классификатор "
            "в ожидаемом виде или лист с правилами не первый"
        )

    payload = {
        "source": source,
        "groups": groups,
        "services": sorted({s["service"] for s in services}),
        "rules": rules,
    }
    return ParseResult(payload=payload, unknown_variants=unknown)


def parse_workbook(data: bytes, source: str = "classificator.xlsx") -> ParseResult:
    """Разбирает xlsx, полученный байтами: из файла поставки или из формы загрузки.

    Берётся активный лист, как и в скрипте сборки: правила в исходнике лежат
    на первом листе, а остальные листы содержат справочные сведения.
    """
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 — openpyxl не объединяет свои ошибки одним типом
        raise ParseError(f"Файл не читается как книга Excel (xlsx): {exc}") from exc
    try:
        rows = list(workbook.active.iter_rows(values_only=True))
    finally:
        workbook.close()
    return parse_rows(rows, source)
