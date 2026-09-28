"""Оркестрация ИИ-операций backend_new: генерация, диалог, эталон, оценка.

Все обращения к ИИ выполняются HTTP-клиентом AIServiceClient к stateless
микросервису ai_service (см. plans/plan3_ai_microservice.md): ключ провайдера
хранится только в микросервисе. Состояние диалога хранит клиент/БД —
функции микросервиса stateless.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import EventClass, EventFeature1, EventFeature2, EventFeature3, EventType, Service
from app.models.content import StudyTask, TaskEtalon
from app.models.training import IncidentCard
from app.repositories.content import ContentRepository
from app.repositories.training import TrainingRepository
from app.services.ai import AIConfigError, get_ai_client
from app.services.ai import mapping

STAFF_ROLES = {"system_admin", "admin", "teacher"}


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AIConfigError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


def difficulty_to_level(difficulty: int) -> str:
    """Сложность учебной задачи (1..5) -> уровень поведения заявителя."""
    return "easy" if difficulty <= 2 else "medium" if difficulty <= 4 else "hard"


def _serialize_assessment(assessment: dict) -> dict:
    """Готовит заключение ИИ к сохранению в ai_eval_details (JSONB)."""
    payload = {
        "summary": assessment.get("summary", ""),
        "fields": assessment.get("fields", {}),
        "score": assessment.get("score"),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    json.dumps(payload, ensure_ascii=False)  # проверка сериализуемости
    return payload


class AIService:
    """ИИ-операции над учебными задачами и карточками."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._content = ContentRepository(session)
        self._training = TrainingRepository(session)

    # --- Проверка доступности ИИ ---------------------------------------------

    @staticmethod
    async def status() -> dict:
        try:
            return await get_ai_client().status()
        except (AIConfigError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from None

    # --- Вспомогательная загрузка задачи --------------------------------------

    async def _require_task(self, task_id: UUID) -> StudyTask:
        task = await self._content.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Учебная задача не найдена")
        return task

    async def _classification(self, task: StudyTask) -> tuple[dict | None, list[str], str | None]:
        """(incident_class для промптов, названия служб, главная служба)."""
        event_class = feature_1 = feature_2 = feature_3 = event_type = None
        if task.event_class_id is not None:
            event_class = await self._session.get(EventClass, task.event_class_id)
        if event_class is not None:
            event_type = await self._session.get(EventType, event_class.event_type_id)
            feature_1 = await self._session.get(EventFeature1, event_class.event_feature_1_id)
            feature_2 = await self._session.get(EventFeature2, event_class.event_feature_2_id)
            feature_3 = await self._session.get(EventFeature3, event_class.event_feature_3_id)
        service_names = [s.name for s in task.services]
        main_name = None
        if task.main_service_id is not None:
            main = await self._session.get(Service, task.main_service_id)
            main_name = main.name if main else None
        elif event_class is not None and event_class.main_service_id is not None:
            main = await self._session.get(Service, event_class.main_service_id)
            main_name = main.name if main else None
        incident_class = None
        if event_class is not None:
            incident_class = {
                "id": str(event_class.id),
                "title": event_class.name,
                "sign1": (feature_1.statistics_name if feature_1 else "") or "",
                "sign2": feature_2.name if feature_2 else "",
                "sign3": feature_3.name if feature_3 else "",
                "group": event_type.name if event_type else "",
                "services": service_names or ([main_name] if main_name else []),
                "main_service": main_name or (service_names[0] if service_names else ""),
            }
        return incident_class, service_names, main_name

    def _task_snapshot(self, task: StudyTask) -> dict:
        return {
            "caller_message": task.caller_message,
            "aon_phone": task.aon_phone,
            "provided_phone": task.provided_phone,
            "scene_phone": task.scene_phone,
            "caller_full_name": task.caller_full_name,
            "country": task.country,
            "federal_subject": task.federal_subject,
            "locality": task.locality,
            "address_object": task.address_object,
            "administrative_district": task.administrative_district,
            "district": task.district,
            "street": task.street,
            "house": task.house,
            "building": task.building,
            "structure": task.structure,
            "apartment": task.apartment,
            "entrance": task.entrance,
            "floor": task.floor,
            "intercom_code": task.intercom_code,
            "latitude": task.latitude,
            "longitude": task.longitude,
            "descriptive_address": task.descriptive_address,
            "incident_description": task.incident_description,
        }

    # --- Генерация учебной задачи (замена заглушки 501) -----------------------

    async def generate_task(self, task_id: UUID, payload: dict) -> StudyTask:
        task = await self._require_task(task_id)
        incident_class, _service_names, _main = await self._classification(task)
        flags = dict(payload.get("flags") or {})
        if not flags:
            if task.has_victims:
                flags.setdefault("injured", "yes")
            if task.no_access:
                flags.setdefault("no_access", "yes")
        request = {
            "topic": payload.get("topic") or task.incident_description or "",
            "location": payload.get("location") or task.locality or "",
            "flags": flags,
            "index": int(payload.get("index") or 1),
            "total": int(payload.get("total") or 1),
            "incident_class": incident_class,
        }
        try:
            result = await get_ai_client().generate_card(request)
        except (AIConfigError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from None
        values = mapping.ai_content_to_task_values(result["content"])
        values["caller_message"] = result["content"]["report"]
        for column, value in values.items():
            setattr(task, column, value)
        await self._session.commit()
        return await self._require_task(task_id)

    # --- Превью эталона ---------------------------------------------------------

    async def reference_preview(self, task_id: UUID, payload: dict) -> tuple[StudyTask, dict]:
        task = await self._require_task(task_id)
        if not (task.caller_message or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Для эталона заполните сообщение заявителя",
            )
        incident_class, service_names, main_name = await self._classification(task)
        if incident_class is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Выберите класс происшествия в классификаторе (Группа + признаки 1–3)",
            )
        content = mapping.task_to_ai_content(
            self._task_snapshot(task),
            classification=incident_class,
            service_names=service_names,
            main_service_name=main_name,
        )
        phone = payload.get("caller_scenario_phone")
        scenario = {
            "version": 1,
            "phone_callback": mapping.scenario_phone(phone or task.provided_phone, task.id),
        }
        request = {"content": content, "caller_scenario": scenario, "incident_class": incident_class}
        try:
            reference = await get_ai_client().reference_preview(request)
        except (AIConfigError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from None

        etalon = mapping.ai_fields_to_etalon(reference["answer"]["expected_fields"])
        etalon["caller_message"] = task.caller_message
        if task.aon_phone:
            etalon["aon_phone"] = task.aon_phone
        etalon["provided_phone"] = scenario["phone_callback"]
        if task.scene_phone:
            etalon["scene_phone"] = task.scene_phone
        event_class = await self._session.get(EventClass, task.event_class_id) if task.event_class_id else None
        classification_flat = {}
        if event_class is not None:
            event_type = await self._session.get(EventType, event_class.event_type_id)
            feature_1 = await self._session.get(EventFeature1, event_class.event_feature_1_id)
            feature_2 = await self._session.get(EventFeature2, event_class.event_feature_2_id)
            feature_3 = await self._session.get(EventFeature3, event_class.event_feature_3_id)
            classification_flat = mapping.classification_snapshot(
                event_type={"code": event_type.code, "name": event_type.name} if event_type else None,
                feature_1={"statistics_name": feature_1.statistics_name, "operator_label": feature_1.operator_label} if feature_1 else None,
                feature_2={"name": feature_2.name} if feature_2 else None,
                feature_3={"name": feature_3.name} if feature_3 else None,
                event_class={"event_number": event_class.event_number, "name": event_class.name},
                service_names=service_names,
                main_service_name=main_name,
            )
        etalon.update(classification_flat)
        extra_schemas = [
            {"code": s.code, "label": s.label, "field_type": s.field_type, "required": s.required}
            for s in (task.extra_field_schemas or [])
        ]
        for code in (task.extra_fields or {}):
            etalon["extra." + code] = task.extra_fields[code]
        field_schema = mapping.field_schema_for(etalon, extra_schemas)

        if task.etalon is None:
            task.etalon = TaskEtalon(content=etalon, field_schema=field_schema)
        else:
            task.etalon.content = etalon
            task.etalon.field_schema = field_schema
        await self._session.commit()
        return await self._require_task(task_id), reference

    # --- Реплика заявителя ------------------------------------------------------

    async def _caller_reply(self, task: StudyTask, question: str, turns: list, level: str | None) -> dict:
        incident_class, service_names, main_name = await self._classification(task)
        content = mapping.task_to_ai_content(
            self._task_snapshot(task),
            classification=incident_class,
            service_names=service_names,
            main_service_name=main_name,
        )
        request = {
            "content": content,
            "caller_scenario": {"version": 1, "phone_callback": mapping.scenario_phone(task.provided_phone, task.id)},
            "question": question,
            "turns": turns,
            "level": level or difficulty_to_level(task.difficulty),
            "incident_class": incident_class,
        }
        try:
            return await get_ai_client().caller_reply(request)
        except (AIConfigError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from None

    async def caller_reply_for_task(self, task_id: UUID, payload: dict) -> dict:
        task = await self._require_task(task_id)
        return await self._caller_reply(task, payload.get("question") or "", payload.get("turns") or [], payload.get("level"))

    async def caller_reply_for_card(self, card_id: UUID, payload: dict, user) -> dict:
        card = await self._require_dialog_card(card_id, user)
        task = await self._content.get_task(card.study_task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Учебная задача не найдена")
        return await self._caller_reply(task, payload.get("question") or "", payload.get("turns") or [], payload.get("level"))

    # --- Реплика службы ДДС -----------------------------------------------------

    async def service_reply_for_card(self, card_id: UUID, payload: dict, user) -> dict:
        card = await self._require_dialog_card(card_id, user)
        task = await self._content.get_task(card.study_task_id)
        service_info = payload.get("service") or {}
        service = {
            "name": service_info.get("name") or "Учебная служба",
            "role": service_info.get("role") or "диспетчер службы",
            "knowledge": service_info.get("knowledge")
            or "Знает только свою должность и компетенцию. О происшествии узнаёт из звонка диспетчера ДДС.",
        }
        level = payload.get("level") or (difficulty_to_level(task.difficulty) if task else "medium")
        try:
            result = await get_ai_client().service_reply({
                "service": service,
                "persona": payload.get("persona") or "сотрудник учебной службы",
                "level": level,
                "history": payload.get("history") or [],
                "question": payload.get("question") or "",
                "mode": payload.get("mode") or "clear",
                "attempt": int(payload.get("attempt") or 1),
            })
        except (AIConfigError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from None
        return {"reply": result["reply"], "delivered": result["delivered"], "mode": payload.get("mode") or "clear"}

    # --- Предварительная оценка ИИ ----------------------------------------------

    async def assess_card(self, card_id: UUID, payload: dict) -> tuple[IncidentCard, dict]:
        card = await self._training.get_card(card_id)
        if card is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Карточка не найдена")
        if card.status == "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Предварительная оценка доступна после отправки карточки",
            )
        task = await self._content.get_task(card.study_task_id)
        if task is None or task.etalon is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="У задачи нет утверждённого эталона — сначала создайте эталон",
            )
        labels = mapping.etalon_labels(task.etalon.field_schema)
        if not labels:
            labels = {k: mapping.COLUMN_LABELS.get(k, k) for k in task.etalon.content}
        try:
            assessment = await get_ai_client().assess({
                "labels": labels,
                "card": card.content or {},
                "expected": task.etalon.content,
                "history": payload.get("history") or [],
                "hints_used": int(payload.get("hints_used") or 0),
            })
        except (AIConfigError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from None
        card.ai_score = Decimal(str(assessment["score"]))
        card.ai_eval_details = _serialize_assessment(assessment)
        await self._session.commit()
        card = await self._training.get_card(card_id)
        return card, assessment

    # --- Валидация полей карточки (мастерская, ИИ-формат) -----------------------

    async def validate_fields(self, task_id: UUID, content: dict) -> dict:
        await self._require_task(task_id)
        try:
            valid = await get_ai_client().validate_fields(content)
        except (AIConfigError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from None
        return {"valid": True, "content": valid["content"]}

    # --- Доступ к карточке для диалога ------------------------------------------

    async def _require_dialog_card(self, card_id: UUID, user) -> IncidentCard:
        card = await self._training.get_card(card_id)
        if card is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Карточка не найдена")
        if {role.code for role in user.roles} & STAFF_ROLES:
            return card
        session = await self._training.get_session(card.session_id)
        if session is None or session.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Это не ваша карточка")
        if card.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Карточка уже отправлена: продолжать разговор нельзя",
            )
        return card
