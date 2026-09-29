"""Маппинг между форматом полной карточки ИИ-проекта и моделями backend_new.

ИИ-формат (ключи LABELS: caller_name, city, street, ...) используется в
промптах генерации/диалога/эталона. backend_new хранит задачу в типизированных
колонках StudyTask, а эталон и карточку ученика — в плоском JSONB
(etalon.content / incident_cards.content) с ключами вида caller_full_name,
federal_subject, locality, ... (как в fillEtalonFromTask / collectCardContent
frontend_new). Этот модуль — единственное место перевода между форматами.
Список ключей ИИ-карточки зафиксирован локально: ядро вынесено в ai_service,
поэтому зависимости от card_factory здесь нет.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

UNKNOWN = "Неизвестно"

# Ключи полной карточки ИИ-проекта (эквивалент card_factory.LABELS):
# фиксируется здесь, чтобы mapping не зависел от ядра в ai_service.
AI_LABELS: tuple[str, ...] = (
    "caller_name", "caller_role", "phone_aon", "phone_callback", "phone_scene",
    "country", "region", "city", "object", "district", "area", "street", "house",
    "block", "building", "apartment", "entrance", "floor", "intercom",
    "latitude", "longitude", "address_text", "access",
    "description", "people", "injured", "floors", "extra_signs", "vis_info",
    "external_number", "registered_by", "control_at", "controlled_by", "control_notes",
)
# Значения, которые не нужно записывать в типизированные колонки задачи.
SKIP_VALUES = {
    "",
    "неизвестно",
    "не указан",
    "не указана",
    "не указано",
    "не указаны",
    "не относится",
    "не применимо",
    "не предоставлена",
    "не предоставлено",
    "не определён: вымышленная карточка",
}

# ИИ-ключ -> колонка StudyTask
AI_TO_TASK_COLUMN: dict[str, str] = {
    "caller_name": "caller_full_name",
    "phone_aon": "aon_phone",
    "phone_callback": "provided_phone",
    "phone_scene": "scene_phone",
    "country": "country",
    "region": "federal_subject",
    "city": "locality",
    "object": "address_object",
    "district": "administrative_district",
    "area": "district",
    "street": "street",
    "house": "house",
    "block": "building",
    "building": "structure",
    "apartment": "apartment",
    "entrance": "entrance",
    "floor": "floor",
    "intercom": "intercom_code",
    "address_text": "descriptive_address",
    "description": "incident_description",
}

# ИИ-ключ -> плоский ключ эталона/карточки для полей без типизированной колонки
AI_TO_FLAT: dict[str, str] = {
    "caller_role": "caller_role",
    "access": "access",
    "people": "people",
    "injured": "injured",
    "floors": "floors",
    "extra_signs": "extra_signs",
}

# Плоские ключи классификации (заполняются из классификатора backend_new)
CLASSIFICATION_KEYS = ("event_type", "feature_1", "feature_2", "feature_3", "event_class", "services")

# Подписи плоских ключей эталона/карточки (для field_schema и оценок ИИ)
COLUMN_LABELS: dict[str, str] = {
    "caller_message": "Сообщение заявителя",
    "aon_phone": "Телефон (АОН)",
    "provided_phone": "Телефон (предоставленный)",
    "scene_phone": "Телефон (на месте)",
    "caller_full_name": "ФИО заявителя",
    "incident_description": "Описание со слов заявителя",
    "country": "Страна",
    "federal_subject": "Субъект",
    "locality": "Населённый пункт",
    "address_object": "Объект",
    "administrative_district": "Округ",
    "district": "Район",
    "street": "Улица",
    "house": "Дом",
    "building": "Корпус",
    "structure": "Строение",
    "apartment": "Квартира",
    "entrance": "Подъезд",
    "floor": "Этаж",
    "intercom_code": "Домофон",
    "latitude": "Широта",
    "longitude": "Долгота",
    "descriptive_address": "Описательный адрес",
    "caller_role": "Статус заявителя",
    "access": "Ориентиры / как проехать",
    "people": "Люди внутри / заблокированы",
    "injured": "Пострадавшие",
    "floors": "Этажность здания",
    "extra_signs": "Дополнительные признаки",
    "event_type": "Группа происшествий",
    "feature_1": "Признак 1",
    "feature_2": "Признак 2",
    "feature_3": "Признак 3",
    "event_class": "Класс происшествия",
    "services": "Привлекаемые службы",
}

# Поля, где пустая строка означает «не применимо / не задано»
# (формальные части адреса, координаты и служебные поля регистрации)
OPTIONAL_EMPTY = {
    "block", "building", "apartment", "entrance", "intercom", "floor", "latitude", "longitude",
    "external_number", "registered_by", "control_at", "controlled_by", "control_notes",
}

PHONE_PATTERN = re.compile(r"\+7 \(000\) \d{3}-\d{2}-\d{2}")


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ("" if value is None else str(value))


def _skip(value: str) -> bool:
    return value.strip().rstrip(".").lower() in SKIP_VALUES


def synthetic_phone(seed: UUID | str) -> str:
    """Условный учебный телефон для перезвона (код 000 — явно вымышленный)."""
    digits = re.sub(r"[^0-9a-f]", "", str(seed).lower())[:12].ljust(12, "0")
    part = str(int(digits, 16)).zfill(12)
    return f"+7 (000) {part[0:3]}-{part[3:5]}-{part[5:7]}"


def scenario_phone(provided_phone: str | None, seed: UUID | str) -> str:
    phone = (provided_phone or "").strip()
    return phone if PHONE_PATTERN.fullmatch(phone) else synthetic_phone(seed)


def ai_content_to_task_values(content: dict) -> dict[str, Any]:
    """ИИ content (card_factory.generate) -> значения колонок StudyTask."""
    fields = content.get("fields", {})
    values: dict[str, Any] = {}
    for ai_key, column in AI_TO_TASK_COLUMN.items():
        value = _clean(fields.get(ai_key))
        if _skip(value):
            continue
        values[column] = value
    for key in ("latitude", "longitude"):
        raw = _clean(fields.get(key))
        if raw and not _skip(raw):
            try:
                values[key] = float(raw.replace(",", "."))
            except ValueError:
                continue
    flags = content.get("flags", {})
    if isinstance(flags, dict):
        if flags.get("injured") == "yes":
            values["has_victims"] = True
        if flags.get("no_access") == "yes":
            values["no_access"] = True
    return values


def ai_fields_to_etalon(fields: dict) -> dict[str, Any]:
    """Поля ИИ-эталона (expected_fields) -> плоский эталон backend_new."""
    etalon: dict[str, Any] = {}
    for ai_key, column in AI_TO_TASK_COLUMN.items():
        row = fields.get(ai_key)
        value = row.get("value") if isinstance(row, dict) else None
        etalon[column] = _clean(value)
    for ai_key, flat_key in AI_TO_FLAT.items():
        row = fields.get(ai_key)
        value = row.get("value") if isinstance(row, dict) else None
        etalon[flat_key] = _clean(value)
    return etalon


def classification_snapshot(
    *,
    event_type: dict | None,
    feature_1: dict | None,
    feature_2: dict | None,
    feature_3: dict | None,
    event_class: dict | None,
    service_names: list[str],
    main_service_name: str | None,
) -> dict[str, Any]:
    """Текстовое представление классификации для эталона (как во frontend)."""
    snapshot: dict[str, Any] = {}
    if event_type:
        snapshot["event_type"] = f"Г{event_type.get('code')} {event_type.get('name')}"
    if feature_1:
        snapshot["feature_1"] = feature_1.get("statistics_name") or feature_1.get("operator_label")
    if feature_2:
        snapshot["feature_2"] = feature_2.get("name")
    if feature_3:
        snapshot["feature_3"] = feature_3.get("name")
    if event_class:
        snapshot["event_class"] = f"№{event_class.get('event_number')} {event_class.get('name')}"
    if service_names:
        snapshot["services"] = list(service_names)
    elif main_service_name:
        snapshot["services"] = [main_service_name]
    return {k: v for k, v in snapshot.items() if v}


def field_schema_for(etalon: dict, extra_schemas: list[dict] | None = None) -> list[dict]:
    """Схема полей эталона/карточки: [{code, label, field_type, required}]."""
    schema: list[dict] = []
    seen: set[str] = set()
    extra_by_code = {str(s.get("code")): s for s in (extra_schemas or [])}
    for key in etalon:
        if key.startswith("extra."):
            extra = extra_by_code.get(key[len("extra."):], {})
            schema.append({
                "code": key,
                "label": extra.get("label") or key,
                "field_type": extra.get("field_type") or "text",
                "required": bool(extra.get("required")),
            })
        else:
            schema.append({
                "code": key,
                "label": COLUMN_LABELS.get(key, key),
                "field_type": "number" if key in ("latitude", "longitude") else "text",
                "required": False,
            })
        seen.add(key)
    for code, extra in extra_by_code.items():
        key = "extra." + code
        if key not in seen:
            schema.append({
                "code": key,
                "label": extra.get("label") or code,
                "field_type": extra.get("field_type") or "text",
                "required": bool(extra.get("required")),
            })
    return schema


def task_to_ai_content(
    task: dict,
    *,
    classification: dict | None = None,
    service_names: list[str] | None = None,
    main_service_name: str | None = None,
) -> dict:
    """Снимок задачи (dict колонок StudyTask) -> ИИ content для промптов."""
    classification = classification or {}
    service_names = service_names or []
    fields: dict[str, str] = {}
    for ai_key in AI_LABELS:
        fields[ai_key] = "" if ai_key in OPTIONAL_EMPTY else UNKNOWN
    for ai_key, column in AI_TO_TASK_COLUMN.items():
        value = task.get(column)
        if value is not None and str(value).strip() and not _skip(str(value)):
            fields[ai_key] = str(value)
    fields["phone_aon"] = task.get("aon_phone") or "Не определён"
    fields["phone_callback"] = task.get("provided_phone") or "Не указан"
    fields["phone_scene"] = task.get("scene_phone") or "Не указан"
    fields["vis_info"] = "Не предоставлена"
    class_ids = [classification["id"]] if classification.get("id") else []
    return {
        "title": classification.get("title") or "Учебная карточка",
        "report": task.get("caller_message") or "",
        "fields": fields,
        "class_ids": class_ids,
        "services": list(service_names),
        "main_service": main_service_name or (service_names[0] if service_names else ""),
    }


def etalon_labels(field_schema: list[dict] | None) -> dict[str, str]:
    """field_schema -> {код: подпись} для оценок ИИ и UI."""
    labels = {}
    for row in field_schema or []:
        code = str(row.get("code") or "").strip()
        if code:
            labels[code] = str(row.get("label") or code)
    return labels
