"""Формирование карточек моделью — в фоне, по одной, с сохранением каждой.

Запрос преподавателя возвращается сразу с номером задания; дальше карточки
пишутся последовательно: модель на процессоре не ускоряется от параллельных
запросов, а очередь из пяти одновременных только размазывает время так, что
первая карточка появляется не через минуту, а через пять. Каждая готовая
сохраняется черновиком немедленно — обрыв связи или перезапуск сервера
теряют не пачку, а одну карточку.
"""

from __future__ import annotations

import logging
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.llm import get_llm_provider
from app.models.audit import AuditAction
from app.models.base import utcnow
from app.models.training import GenerationJob, GenerationState, Scenario, ScenarioSource
from app.models.user import DispatchService, User
from app.services import audit
from app.services.classifier_versions import current_ekp
from app.services.generation import DraftScenario, draft_from_rule, pick_rules

logger = logging.getLogger(__name__)


def save_draft(db: Session, draft: DraftScenario, service: DispatchService, author: User) -> Scenario:
    scenario = Scenario(
        title=draft.incident_type,
        incident_type=draft.incident_type,
        ekp_rule_number=draft.ekp_rule_number,
        address=draft.address,
        description=draft.description,
        caller=draft.caller,
        target_service=service,
        expected_primary_status=str(draft.expected_primary_status),
        is_profile=draft.is_profile,
        required_comment_points=list(draft.required_comment_points),
        difficulty=draft.difficulty,
        source=ScenarioSource.GENERATED,
        author=author,
    )
    db.add(scenario)
    return scenario


def start(
    db: Session, *, teacher: User, group: str, count: int, difficulty: int, service: DispatchService
) -> GenerationJob:
    """Заводит задание. Саму работу запускает вызывающий — фоновой задачей."""
    job = GenerationJob(
        teacher=teacher,
        group=group,
        difficulty=difficulty,
        service=service,
        requested=count,
    )
    db.add(job)
    db.commit()
    return job


def active_for(db: Session, teacher: User) -> list[GenerationJob]:
    """Незавершённые задания преподавателя — чтобы страница после перезагрузки
    подхватила ход работы, а не показала пустую кнопку."""
    return list(
        db.scalars(
            select(GenerationJob)
            .where(
                GenerationJob.teacher_id == teacher.id,
                GenerationJob.state == GenerationState.RUNNING,
            )
            .order_by(GenerationJob.id)
        ).all()
    )


async def run(job_id: int) -> None:
    """Выполняет задание: карточка за карточкой, каждая сразу в базу.

    Открывает собственную сессию: выполняется после ответа клиенту, когда
    сессия запроса уже закрыта.
    """
    with SessionLocal() as db:
        job = db.get(GenerationJob, job_id)
        if job is None or job.state is not GenerationState.RUNNING:
            return
        teacher, service = job.teacher, job.service
        try:
            ekp = current_ekp(db)
            rng = random.Random()
            rules = pick_rules(job.group, job.requested, service.classifier_name, rng, ekp)
            provider = get_llm_provider()
            for rule in rules:
                draft = await draft_from_rule(
                    provider, rule, service.classifier_name, job.difficulty,
                    rng=random.Random(rng.random()),
                )
                job.finished += 1
                if draft is not None:
                    scenario = save_draft(db, draft, service, teacher)
                    db.flush()
                    job.created += 1
                    # Новый список, а не append: JSON-столбец замечает
                    # только присваивание.
                    job.scenario_ids = [*job.scenario_ids, scenario.id]
                db.commit()
            job.state = GenerationState.DONE
        except Exception as failure:  # noqa: BLE001 — задание обязано завершиться с ошибкой, а не зависнуть
            logger.exception("Формирование карточек прервано: %s", failure)
            db.rollback()
            job = db.get(GenerationJob, job_id)
            job.state = GenerationState.FAILED
            job.error = str(failure)[:500] or type(failure).__name__
        job.finished_at = utcnow()
        audit.record(
            db,
            AuditAction.SCENARIO_GENERATED,
            actor=teacher,
            object_type="scenario",
            detail={
                "группа": job.group,
                "служба": service.name,
                "запрошено": job.requested,
                "создано": job.created,
                "итог": str(job.state),
            },
        )
        db.commit()
