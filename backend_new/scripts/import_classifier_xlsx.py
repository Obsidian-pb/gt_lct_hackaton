"""Импорт классификатора происшествий из TZ/datasets/клссы событий.xlsx.

Заполняет схемы catalog:
  - event_types (группы происшествий, код «Г»)
  - event_features_1 / event_features_2 / event_features_3 (признаки 1-3)
  - services (по кодам главной службы)
  - event_classes (классы событий) с проставлением main_service_id
    и связей event_class_services.

Идемпотентный: повторный запуск не создаёт дублей (upsert по уникальным ключам).

Запуск из каталога backend_new:
    .venv\\Scripts\\python.exe scripts/import_classifier_xlsx.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import openpyxl

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db.session import async_session_factory  # noqa: E402
from app.models.catalog import (  # noqa: E402
    EventClass,
    EventFeature1,
    EventFeature2,
    EventFeature3,
    EventType,
    Service,
    event_class_services,
)

DEFAULT_WORKBOOK = BACKEND_ROOT.parent / "TZ" / "datasets" / "клссы событий.xlsx"

SERVICE_NAMES: dict[str, str] = {
    "MCHS": "МЧС России (пожарная охрана)",
    "AMBULANCE": "Скорая медицинская помощь",
    "Police": "Полиция",
    "Dep.tszn": "Департамент труда и социальной защиты",
    "DepEco": "Департамент природопользования и охраны окружающей среды",
    "MOSGAZ": "АО «Мосгаз»",
    "MOSGORTRANS": "ГУП «Мосгортранс»",
    "MOSLIFT": "АО «Мослифт»",
    "MOSVODOCANAL": "АО «Мосводоканал»",
    "MOSVODOSTOK": "ГУП «Мосводосток»",
    "MOEK": "ПАО «МОЭК»",
    "MOESK": "ПАО «Россети Московский регион»",
    "MOSCOLLECTOR": "АО «Москоллектор»",
    "MSPPN": "ГБУ «МСППН»",
    "MZD": "ОАО «РЖД»",
    "OEK": "АО «ОЭК»",
    "METRO": "ГУП «Московский метрополитен»",
    "MGTS": "ПАО «МГТС»",
    "AUTOROADS": "ГБУ «Автомобильные дороги»",
    "GKH": "Городское хозяйство",
    "GORMOST": "ГБУ «Гормост»",
    "ZEMP": "Центр экстренной медицинской помощи",
    "ZODD": "ГКУ «ЦОДД»",
}


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    return text or None


def to_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_workbook(path: Path) -> dict[str, Any]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))

    group_names: dict[int, str] = {}
    features1: dict[tuple[int, int], tuple[str | None, str | None]] = {}
    features2: dict[tuple[int, int, int], str | None] = {}
    features3: dict[tuple[int, int, int, int], str | None] = {}
    classes: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    service_codes: set[str] = set()

    for raw in rows:
        if raw is None:
            continue
        if not any(raw[:4]):
            # Строка-заголовок группы: первые 4 колонки пусты, E — код группы, F — название
            code = to_int(raw[4])
            name = clean(raw[5])
            if code is not None and name:
                group_names[code] = name
            continue
        g = to_int(raw[0])
        if g is None:
            continue
        f1 = to_int(raw[1], 0) or 0
        f2 = to_int(raw[2], 0) or 0
        f3 = to_int(raw[3], 0) or 0
        label1 = clean(raw[6]) or clean(raw[7])
        label2 = clean(raw[7])
        label3 = clean(raw[8])
        main_service = clean(raw[13])
        scenario_code = clean(raw[12])

        features1[(g, f1)] = (label1, label1)
        features2[(g, f1, f2)] = label2
        features3[(g, f1, f2, f3)] = label3

        key = (g, f1, f2, f3)
        classes.setdefault(key, {
            "event_number": to_int(raw[4], 0) or 0,
            "name": clean(raw[5]) or "",
            "main_service": main_service,
            "scenario_code": scenario_code,
        })
        if main_service:
            for part in main_service.split(","):
                code = part.strip()
                if code:
                    service_codes.add(code)

    return {
        "group_names": group_names,
        "features1": features1,
        "features2": features2,
        "features3": features3,
        "classes": classes,
        "service_codes": service_codes,
    }


async def import_classifier(session: AsyncSession, data: dict[str, Any]) -> dict[str, int]:
    counts = {"event_types": 0, "features1": 0, "features2": 0, "features3": 0,
              "services": 0, "event_classes": 0, "class_services": 0}

    # --- Службы ---
    svc_by_code: dict[str, Service] = {
        s.code: s for s in (await session.execute(select(Service))).scalars().all()
    }
    for code in sorted(data["service_codes"]):
        if code in svc_by_code:
            continue
        svc = Service(code=code, name=SERVICE_NAMES.get(code, code),
                      description="Импорт из клссы событий.xlsx")
        session.add(svc)
        svc_by_code[code] = svc
        counts["services"] += 1
    await session.flush()

    # --- Группы происшествий (код Г) ---
    types_by_code: dict[int, EventType] = {
        t.code: t for t in (await session.execute(select(EventType))).scalars().all()
    }
    type_id_by_code = {code: t.id for code, t in types_by_code.items()}
    for code, name in data["group_names"].items():
        if code not in types_by_code:
            t = EventType(code=code, name=name)
            session.add(t)
            types_by_code[code] = t
            counts["event_types"] += 1
    await session.flush()
    for code, t in types_by_code.items():
        type_id_by_code[code] = t.id

    # --- Признак 1: ключ (код группы, код признака) ---
    f1_by_key: dict[tuple[int, int], EventFeature1] = {}
    existing_f1 = (await session.execute(select(EventFeature1))).scalars().all()
    for f in existing_f1:
        for code, tid in type_id_by_code.items():
            if tid == f.event_type_id:
                f1_by_key[(code, f.code)] = f
                break
    for (g, c1), (stat_name, op_label) in data["features1"].items():
        if stat_name is None:
            continue
        key = (g, c1)
        if key in f1_by_key:
            continue
        if g not in types_by_code:
            continue
        f = EventFeature1(event_type_id=types_by_code[g].id, code=c1,
                          statistics_name=stat_name, operator_label=op_label)
        session.add(f)
        f1_by_key[key] = f
        counts["features1"] += 1
    await session.flush()

    # --- Признак 2: ключ (код группы, код п1, код п2) ---
    f2_by_key: dict[tuple[int, int, int], EventFeature2] = {}
    f1_id_to_key = {f.id: k for k, f in f1_by_key.items()}
    existing_f2 = (await session.execute(select(EventFeature2))).scalars().all()
    for f in existing_f2:
        parent = f1_id_to_key.get(f.event_feature_1_id)
        if parent is not None:
            f2_by_key[(parent[0], parent[1], f.code)] = f
    for (g, c1, c2), name in data["features2"].items():
        if name is None:
            continue
        key = (g, c1, c2)
        if key in f2_by_key:
            continue
        if (g, c1) not in f1_by_key:
            continue
        f = EventFeature2(event_feature_1_id=f1_by_key[(g, c1)].id, code=c2, name=name)
        session.add(f)
        f2_by_key[key] = f
        counts["features2"] += 1
    await session.flush()

    # --- Признак 3: ключ (код группы, коды п1, п2, п3) ---
    f3_by_key: dict[tuple[int, int, int, int], EventFeature3] = {}
    f2_id_to_key = {f.id: k for k, f in f2_by_key.items()}
    existing_f3 = (await session.execute(select(EventFeature3))).scalars().all()
    for f in existing_f3:
        parent = f2_id_to_key.get(f.event_feature_2_id)
        if parent is not None:
            f3_by_key[(parent[0], parent[1], parent[2], f.code)] = f
    for (g, c1, c2, c3), name in data["features3"].items():
        if name is None:
            continue
        key = (g, c1, c2, c3)
        if key in f3_by_key:
            continue
        if (g, c1, c2) not in f2_by_key:
            continue
        f = EventFeature3(event_feature_2_id=f2_by_key[(g, c1, c2)].id, code=c3, name=name)
        session.add(f)
        f3_by_key[key] = f
        counts["features3"] += 1
    await session.flush()

    # --- Классы событий ---
    existing_classes = {
        (type_id_by_code.get(c.event_type_id),
         c.event_feature_1_id, c.event_feature_2_id, c.event_feature_3_id): c
        for c in (await session.execute(select(EventClass))).scalars().all()
    }
    links: list[tuple[EventClass, Any]] = []
    for (g, c1, c2, c3), info in data["classes"].items():
        key = (g, c1, c2, c3)
        f1_id = f1_by_key[(g, c1)].id if (g, c1) in f1_by_key else None
        f2_id = f2_by_key[(g, c1, c2)].id if (g, c1, c2) in f2_by_key else None
        f3_id = f3_by_key[(g, c1, c2, c3)].id if (g, c1, c2, c3) in f3_by_key else None
        if f1_id is None or f2_id is None or f3_id is None:
            continue
        if (g, f1_id, f2_id, f3_id) in existing_classes:
            continue
        main_service_id = None
        if info["main_service"]:
            first = info["main_service"].split(",")[0].strip()
            if first in svc_by_code:
                main_service_id = svc_by_code[first].id
        cls = EventClass(
            event_number=info["event_number"],
            event_type_id=types_by_code[g].id,
            event_feature_1_id=f1_id,
            event_feature_2_id=f2_id,
            event_feature_3_id=f3_id,
            name=info["name"] or "Без наименования",
            scenario_code=info["scenario_code"],
            main_service_id=main_service_id,
        )
        session.add(cls)
        counts["event_classes"] += 1
        if main_service_id is not None:
            links.append((cls, main_service_id))
            counts["class_services"] += 1
    await session.flush()  # присвоить id новым классам
    for cls, service_id in links:
        await session.execute(event_class_services.insert().values(
            event_class_id=cls.id, service_id=service_id))
    await session.commit()
    return counts


async def main() -> None:
    path = DEFAULT_WORKBOOK
    if not path.exists():
        print(f"Файл не найден: {path}")
        raise SystemExit(1)
    print(f"Читаю {path} ...")
    data = parse_workbook(path)
    print(
        f"Групп: {len(data['group_names'])}, "
        f"признаков 1: {len(data['features1'])}, признаков 2: {len(data['features2'])}, "
        f"признаков 3: {len(data['features3'])}, классов: {len(data['classes'])}, "
        f"кодов служб: {len(data['service_codes'])}"
    )
    async with async_session_factory() as session:
        counts = await import_classifier(session, data)
    print("Импорт завершён:", counts)


if __name__ == "__main__":
    asyncio.run(main())