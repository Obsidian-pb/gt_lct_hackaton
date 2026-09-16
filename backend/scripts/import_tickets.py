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
                if match is None or not match.get("rule_number") or key in existing:
                    skipped += 1
                    continue

                rule = ekp.rule(match["rule_number"])
                existing.add(key)
                confident = match.get("verified") in VERIFIED_MARKS
                # Уточнённый адрес оператор выясняет в разговоре, поэтому
                # в карточку он попадает как подсказка, а не как данность.
                address = call["address"]
                if clarified := call.get("address_clarified"):
                    address = f"{address} (при уточнении: {clarified})"

                scenario = Scenario(
                    title=title,
                    mode=TrainingMode.OPERATOR,
                    incident_type="",  # оператор определяет тип сам
                    ekp_rule_number=rule.number,
                    address=address,
                    description=call["situation"],
                    caller=call["situation"].split(",")[-1].strip()[:250],
                    target_service=service,
                    expected_primary_status="Принята",
                    difficulty=2 if confident else 3,
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
