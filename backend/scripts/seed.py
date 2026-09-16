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
    TrainingMode,
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


# Вызовы из экзаменационных билетов Службы 112. Тексты взяты дословно —
# это настоящие учебные задачи, а не выдуманные. Эталон задан номером
# правила классификатора, поэтому проверка классификации объективна.
CALLS = [
    {
        "title": "Билет 1, вызов 1: возгорание мусорного контейнера",
        "ekp_rule_number": 1010101,
        "legend": (
            "Возгорание мусорного контейнера, пострадавших нет, "
            "Сидоров Иван Сергеевич, 916-126-34-71"
        ),
        "address": "Москва, Депо, около ст. Москва-Пассажирская Киевская",
        "caller": "Сидоров Иван Сергеевич, 916-126-34-71",
        "difficulty": 1,
    },
    {
        "title": "Билет 2, вызов 1: задымление мусоропровода",
        "ekp_rule_number": 1050602,
        "legend": (
            "Задымление мусоропровода в жилом доме, в доме 17 этажей, заявитель "
            "находится на 7-м этаже. Открытого пламени не видит, пострадавших "
            "людей нет. Ким Олег Юрьевич, 916-126-34-71"
        ),
        "address": "Москва, ул. Берзарина, дом 21, корп. 1, под. 3, домофон 68",
        "caller": "Ким Олег Юрьевич, 916-126-34-71",
        "difficulty": 3,
    },
    {
        "title": "Билет 4, вызов 1: горит балкон",
        "ekp_rule_number": 1050201,
        "legend": (
            "Горит балкон и два окна рядом на 13-м этаже, открытое пламя, "
            "пострадавших не видят, наблюдают с улицы. Этажность 14, дом "
            "газифицирован. Сидорова Анна Викторовна, 916-126-34-71"
        ),
        "address": "Москва, ул. Грина, дом 11 (в доме библиотека № 193)",
        "caller": "Сидорова Анна Викторовна, 916-126-34-71",
        "difficulty": 2,
    },
    {
        "title": "Билет 30, вызов 2: наезд на пешехода",
        "ekp_rule_number": 2020100,
        "legend": (
            "Наезд на пешехода, мужчина без сознания, на месте ваз 2110 красный "
            "а128 аа177. Иванова Елена Сергеевна, 916-896-32-54"
        ),
        "address": "Москва, ул. Тюменская на пересечении с Тюменским проездом",
        "caller": "Иванова Елена Сергеевна, 916-896-32-54",
        "difficulty": 2,
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

        for item in CALLS:
            call = Scenario(
                title=item["title"],
                mode=TrainingMode.OPERATOR,
                incident_type="",  # оператор определяет тип сам
                ekp_rule_number=item["ekp_rule_number"],
                address=item["address"],
                description=item["legend"],
                caller=item["caller"],
                target_service=service,
                # Эталонный статус в этом режиме не используется: оператор
                # не проставляет статус реагирования, а классифицирует вызов.
                expected_primary_status=str(S.ACCEPTED),
                difficulty=item["difficulty"],
                deadline_seconds=180,
                source=ScenarioSource.TICKET,
                author=teacher,
                approved_by=teacher,
                approved_at=utcnow(),
            )
            scenarios.append(call)
            db.add(call)
        db.flush()

        # Карточки разделены по режимам: занятие диспетчера и занятие
        # оператора живут отдельно, смешивать их нельзя.
        dispatcher_cards = [x for x in scenarios if x.mode is TrainingMode.DISPATCHER]
        operator_cards = [x for x in scenarios if x.mode is TrainingMode.OPERATOR]
        learners = [users["student"], users["student2"]]

        # Два занятия идут прямо сейчас, чтобы у обучающегося сразу была работа,
        # и одно остаётся черновиком — на нём преподаватель показывает запуск
        # занятия вживую.
        started = utcnow()
        running = []
        for title, mode, cards, interval in (
            (
                "Практическое занятие: работа с карточками на АРМ-112",
                TrainingMode.DISPATCHER,
                dispatcher_cards,
                20,
            ),
            (
                "Практическое занятие: приём вызовов по номеру 112",
                TrainingMode.OPERATOR,
                operator_cards,
                60,
            ),
        ):
            session = TrainingSession(
                title=title,
                mode=mode,
                teacher=teacher,
                state=SessionState.ACTIVE,
                pickup_deadline_seconds=30,
                handling_deadline_seconds=180,
                call_interval_seconds=interval,
                started_at=started,
            )
            session.students = learners
            session.scenarios = cards
            db.add(session)
            running.append((session, cards, interval))
        db.flush()

        for session, cards, interval in running:
            for student in learners:
                for offset, scenario in enumerate(cards):
                    # Вызовы поступали потоком: первые уже давно, последние
                    # только что — обучающийся застаёт занятие в середине.
                    db.add(
                        Attempt(
                            session=session,
                            student=student,
                            scenario=scenario,
                            issued_at=started - timedelta(seconds=offset * interval),
                        )
                    )

        draft = TrainingSession(
            title="Смена с высокой нагрузкой (готово к запуску)",
            mode=TrainingMode.DISPATCHER,
            teacher=teacher,
            state=SessionState.DRAFT,
            pickup_deadline_seconds=30,
            handling_deadline_seconds=180,
            # Вызов каждые пять секунд: успеть всё заведомо нельзя, и занятие
            # проверяет умение расставлять приоритеты.
            call_interval_seconds=5,
        )
        draft.students = learners
        draft.scenarios = dispatcher_cards
        db.add(draft)

        db.commit()

    source = "из DEMO_PASSWORD" if DEMO_PASSWORD else "совпадает с логином"
    print(f"Готово. Учебные учётные записи (пароль {source}):")
    for login, full_name, role, _ in USERS:
        print(f"  {login:9s} {str(role):8s} {full_name}")


if __name__ == "__main__":
    seed()
