"""Наполнение учебного стенда демонстрационными данными.

Сценарии взяты из раздела «Примеры нарушений при обработке карточки
происшествия» памятки ГБУ «Система 112»: для каждого известен разбор
специалиста отдела контроля, то есть эталон не выдуман, а документирован.
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.models.training import (  # noqa: E402
    Attempt,
    Scenario,
    ScenarioSource,
    SessionState,
    TrainingSession,
)
from app.models.user import DispatchService, Role, User  # noqa: E402
from app.services.response_status import ResponseStatus as S  # noqa: E402

SERVICE_NAME = "ДДС района Чертаново Южное"

# Учебные службы и их названия в классификаторе. Районные ДДС поимённо в ЕКП
# не значатся, они проходят как территориальные органы власти и оповещаются
# почти обо всём. Аварийные службы, наоборот, узкопрофильные — на них хорошо
# видно, что корректный отказ от непрофильного происшествия тоже навык.
SERVICES = [
    (SERVICE_NAME, "Территориальные ОИВ"),
    ("Мосводоканал", "Мосводоканал"),
    ("Мослифт", "Мослифт"),
]

# Пароль учебных учётных записей. Совпадение с логином допустимо только
# на локальной машине: стенд публикуется в интернете, и там DEMO_PASSWORD
# обязателен — иначе учётка администратора подбирается с первой попытки.
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD")

USERS = [
    ("admin", "Администратор системы", Role.ADMIN, None),
    ("teacher", "Глущенко О. И., преподаватель", Role.TEACHER, None),
    ("student", "Иванов И. И., диспетчер", Role.STUDENT, SERVICE_NAME),
    ("student2", "Петрова А. С., диспетчер", Role.STUDENT, "Мослифт"),
]

SCENARIOS = [
    {
        "title": "Застревание в лифте",
        "ekp_rule_number": 14100100,
        "incident_type": "Застревание в лифте",
        "address": "Москва, ул. Берзарина, д. 21, корп. 1, под. 3",
        "description": (
            "Застряли в лифте между 5 и 6 этажом, два человека, "
            "медицинская помощь не требуется."
        ),
        "caller": "Ким Олег Юрьевич, 916-126-34-71",
        "expected_primary_status": S.REJECTED,
        "is_profile": False,
        "required_comment_points": [
            "лифты в доме обслуживает другая организация",
            "информация передана в диспетчерскую «Практика»",
        ],
        "difficulty": 2,
    },
    {
        "title": "Сработала пожарная сигнализация",
        "ekp_rule_number": 1051600,
        "incident_type": "пожарная сигнализация (жилой дом)",
        "address": "Москва, ул. Академика Янгеля, д. 6, корп. 2",
        "description": (
            "Сработала пожарная сигнализация в жилом доме, признаков возгорания "
            "нет, поступают повторные обращения жильцов."
        ),
        "caller": "Сидорова Анна Викторовна, 916-320-12-83",
        "expected_primary_status": S.REJECTED,
        "is_profile": False,
        "required_comment_points": [
            "дом обслуживает управляющая компания «ПИК»",
            "информация передана в диспетчерскую управляющей компании",
        ],
        "difficulty": 2,
    },
    {
        "title": "Оборван провод во дворе",
        "ekp_rule_number": 14110301,
        "incident_type": "Обрыв проводов (двор)",
        "address": "Москва, Варшавское шоссе, д. 152, двор",
        "description": (
            "Во дворе жилого дома оборван провод, назначение неизвестно, "
            "провод висит на высоте около двух метров."
        ),
        "caller": "Соколов Иван Петрович, 916-896-32-54",
        "expected_primary_status": S.ACCEPTED,
        "is_profile": True,
        "required_comment_points": [
            "провод принадлежит «Ростелеком»",
            "информация передана по принадлежности",
        ],
        "difficulty": 3,
    },
    {
        "title": "Прорыв трубы с горячей водой",
        "ekp_rule_number": 14020300,
        "incident_type": "Течь (прорыв трубы) в квартире (подъезде подвале)",
        "address": "Москва, ул. Днепропетровская, д. 3, корп. 5, под. 2",
        "description": (
            "Прорыв трубы с горячей водой в подвале жилого дома, заливает подъезд, "
            "звонки поступают в течение нескольких часов."
        ),
        "caller": "Иванова Елена Сергеевна, 916-896-32-54",
        "expected_primary_status": S.ACCEPTED,
        "is_profile": True,
        "expects_progress_statuses": True,
        "required_comment_points": [
            "работы ведёт аварийная бригада",
            "на месте главный инженер",
        ],
        "difficulty": 3,
    },
    {
        "title": "Посторонние граждане в подвале",
        "ekp_rule_number": 15140000,
        "incident_type": "Подозрительные граждане",
        "address": "Москва, ул. Кировоградская, д. 24, подвал",
        "description": "В подвале жилого дома находятся посторонние граждане.",
        "caller": "Смирнова Ольга Ивановна, 903-226-13-83",
        "expected_primary_status": S.ACCEPTED,
        "is_profile": True,
        "required_comment_points": ["принято к реагированию"],
        "difficulty": 1,
    },
]


def seed() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.login == "teacher")):
            print("Стенд уже наполнен, пропускаю.")
            return

        services = {
            name: DispatchService(name=name, ekp_name=ekp) for name, ekp in SERVICES
        }
        db.add_all(services.values())
        db.flush()
        service = services[SERVICE_NAME]

        users: dict[str, User] = {}
        for login, full_name, role, service_name in USERS:
            user = User(
                login=login,
                full_name=full_name,
                hashed_password=hash_password(DEMO_PASSWORD or login),
                role=role,
                service=services.get(service_name) if service_name else None,
            )
            users[login] = user
            db.add(user)
        db.flush()

        teacher = users["teacher"]
        scenarios = []
        for item in SCENARIOS:
            scenario = Scenario(
                title=item["title"],
                incident_type=item["incident_type"],
                ekp_rule_number=item["ekp_rule_number"],
                address=item["address"],
                description=item["description"],
                caller=item["caller"],
                target_service=service,
                expected_primary_status=str(item["expected_primary_status"]),
                is_profile=item["is_profile"],
                expects_progress_statuses=item.get("expects_progress_statuses", False),
                required_comment_points=item["required_comment_points"],
                difficulty=item["difficulty"],
                source=ScenarioSource.MANUAL,
                author=teacher,
                approved_by=teacher,
                approved_at=utcnow(),
            )
            scenarios.append(scenario)
            db.add(scenario)
        db.flush()

        training = TrainingSession(
            title="Практическое занятие: работа с карточками на АРМ-112",
            teacher=teacher,
            state=SessionState.ACTIVE,
            deadline_seconds=30,
            started_at=utcnow(),
        )
        db.add(training)
        db.flush()

        # Карточки выдаются каждому обучающемуся: на демонстрации под разными
        # учётными записями заходят одновременно, и пустая лента у второго
        # выглядела бы поломкой.
        for student in (users["student"], users["student2"]):
            for offset, scenario in enumerate(scenarios):
                db.add(
                    Attempt(
                        session=training,
                        student=student,
                        scenario=scenario,
                        issued_at=utcnow() - timedelta(seconds=offset * 2),
                    )
                )
        db.commit()

    source = "из DEMO_PASSWORD" if DEMO_PASSWORD else "совпадает с логином"
    print(f"Готово. Учебные учётные записи (пароль {source}):")
    for login, full_name, role, _ in USERS:
        print(f"  {login:9s} {str(role):8s} {full_name}")


if __name__ == "__main__":
    seed()
