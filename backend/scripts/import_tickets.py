"""Импорт экзаменационных вызовов в учебные сценарии режима оператора.

Источник — расшифрованные билеты Службы 112 и черновое сопоставление
с классификатором. Сопоставление выполнено машинно и надёжно не на сто
процентов, поэтому сценарий попадает в систему неутверждённым: эталон
подтверждает преподаватель. Это тот же порядок, что и у сгенерированных
карточек, и он предусмотрен техническим заданием.

Вызовы из других регионов не импортируются: правильное действие по ним —
передача по принадлежности, а такого действия тренажёр пока не моделирует,
и оценивать их классификацией значило бы учить неверному.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.models.training import (  # noqa: E402
    CallOutcome,
    Scenario,
    ScenarioSource,
    TrainingMode,
)
from app.models.user import DispatchService, Role, User  # noqa: E402
from app.services.ekp import get_ekp  # noqa: E402

TICKETS = BACKEND_DIR / "data" / "tickets.json"
MATCHES = BACKEND_DIR / "data" / "ticket_rules.json"

# Утверждёнными импортируются только сопоставления, просмотренные человеком.
# Автоматическая проверка «слова признаков встречаются в тексте» была
# отвергнута: задымление в торговом центре, названное пожаром, её проходило,
# потому что слова про торговый центр совпадали, а тип был неверный.
VERIFIED_MARKS = {"выверено", "исправлено"}

# Вызовы-ловушки: правильное действие по ним — не классификация.
#
# Восемнадцать происходят в других субъектах: Москва их не обслуживает,
# вызов передаётся по принадлежности. Один не является происшествием
# для Системы-112 и не регистрируется вовсе.
#
# Пометка в расшифровке сделана человеком и записана свободно — «Рязань»,
# «не зона ответственности Москвы». Здесь она приводится к названию субъекта,
# которое обучающийся и должен назвать. Соответствие задано поимённо, а не
# выведено разбором строки: ошибиться тут значит научить неверному,
# и лучше упасть при импорте, чем завести неправильный эталон.
NOT_AN_INCIDENT = "не является происшествием"

TRAP_SUBJECTS = {
    "Московская область": "Московская область",
    "Тульская область": "Тульская область",
    "Рязанская область": "Рязанская область",
    "Владимирская область": "Владимирская область",
    "Волгоградская область": "Волгоградская область",
    # Записано городом, а обслуживает субъект.
    "Рязань": "Рязанская область",
    # Пометка без названия; субъект виден в адресе вызова.
    "не зона ответственности Москвы": "Волгоградская область",
}


def trap_outcome(call: dict) -> tuple[CallOutcome, str | None]:
    """Определяет эталонный исход по пометке расшифровщика."""
    trap = (call.get("trap") or "").strip()
    if not trap:
        return CallOutcome.CLASSIFY, None
    if NOT_AN_INCIDENT in trap:
        return CallOutcome.REJECT, None

    tail = trap.split("—", 1)[1].strip() if "—" in trap else trap
    subject = TRAP_SUBJECTS.get(tail)
    if subject is None:
        raise SystemExit(
            f"Неизвестная пометка ловушки: «{trap}». Добавьте субъект "
            f"в TRAP_SUBJECTS, иначе вызов получит неверный эталон."
        )
    return CallOutcome.REFER, subject


def main(dry_run: bool) -> None:
    tickets = json.loads(TICKETS.read_text(encoding="utf-8"))
    matches = {
        (m["ticket"], m["no"]): m
        for m in json.loads(MATCHES.read_text(encoding="utf-8"))["matches"]
    }
    ekp = get_ekp()

    with SessionLocal() as db:
        teacher = db.scalar(select(User).where(User.role == Role.TEACHER))
        service = db.scalar(select(DispatchService).order_by(DispatchService.id))
        if teacher is None or service is None:
            print("Сначала наполните стенд: scripts/seed.py", file=sys.stderr)
            raise SystemExit(1)

        # Билет опознаётся парой «номер билета, номер вызова». Сверять по типу
        # происшествия нельзя: разные экзаменационные вызовы законно ведут
        # к одному типу — три билета с наездом на пешехода дают одно правило,
        # но это три разные учебные задачи.
        existing: set[tuple[int, int]] = set()
        for row in db.scalars(
            select(Scenario).where(Scenario.source == ScenarioSource.TICKET)
        ).all():
            if found := re.match(r"Билет (\d+), вызов (\d+)", row.title):
                existing.add((int(found.group(1)), int(found.group(2))))

        created = approved = skipped = 0
        for ticket in tickets["tickets"]:
            for call in ticket["calls"]:
                title = f"Билет {ticket['ticket']}, вызов {call['no']}"
                match = matches.get((ticket["ticket"], call["no"]))
                key = (ticket["ticket"], call["no"])
                if key in existing:
                    skipped += 1
                    continue

                outcome, subject = trap_outcome(call)
                # Ловушке правило классификатора не нужно: в московском ЕКП
                # происшествия из другого субъекта нет и быть не может.
                if outcome is CallOutcome.CLASSIFY and (
                    match is None or not match.get("rule_number")
                ):
                    skipped += 1
                    continue

                rule_number = (
                    ekp.rule(match["rule_number"]).number
                    if outcome is CallOutcome.CLASSIFY
                    else None
                )
                existing.add(key)
                # У ловушки эталон — не подобранное машиной правило, а решение
                # не заводить карточку, и оно следует прямо из текста вызова.
                confident = (
                    outcome is not CallOutcome.CLASSIFY
                    or match.get("verified") in VERIFIED_MARKS
                )
                # Уточнённый адрес оператор выясняет в разговоре, поэтому
                # в карточку он попадает как подсказка, а не как данность.
                address = call["address"]
                if clarified := call.get("address_clarified"):
                    address = f"{address} (при уточнении: {clarified})"

                scenario = Scenario(
                    title=title,
                    mode=TrainingMode.OPERATOR,
                    incident_type="",  # оператор определяет тип сам
                    ekp_rule_number=rule_number,
                    expected_outcome=outcome,
                    referral_target=subject,
                    address=address,
                    description=call["situation"],
                    caller=call["situation"].split(",")[-1].strip()[:250],
                    target_service=service,
                    expected_primary_status="Принята",
                    # Ловушки сложнее рядовых вызовов: обучающийся должен
                    # заметить, что происшествие не наше, до всякой опросной карты.
                    difficulty=3 if outcome is not CallOutcome.CLASSIFY else (2 if confident else 3),
                    deadline_seconds=180,
                    source=ScenarioSource.TICKET,
                    author=teacher,
                )
                if confident:
                    scenario.approved_by = teacher
                    scenario.approved_at = utcnow()
                    approved += 1
                else:
                    scenario.teacher_note = (
                        "Тип происшествия подобран машинно и требует решения. "
                        + (match.get("note") or match.get("reason") or "")
                    )
                db.add(scenario)
                created += 1

        if dry_run:
            db.rollback()
            print("Пробный прогон, изменения не сохранены.")
        else:
            db.commit()
        print(
            f"создано {created} (из них утверждено сразу {approved}), "
            f"пропущено {skipped}"
        )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Импорт билетов в учебные сценарии")
    cli.add_argument("--dry-run", action="store_true", help="показать итог без записи")
    main(cli.parse_args().dry_run)
