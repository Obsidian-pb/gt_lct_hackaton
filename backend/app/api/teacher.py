"""Кабинет преподавателя: настройка среды, сценарии, отчёт о занятии."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_teacher
from app.core.db import get_session
from app.llm import get_llm_provider
from app.models.base import utcnow
from app.models.training import (
    Attempt,
    Scenario,
    ScenarioSource,
    TrainingSession,
)
from app.models.user import DispatchService, User
from app.schemas.teacher import (
    CatalogOut,
    CorrectIn,
    GenerateIn,
    GenerateOut,
    ReportOut,
    ScenarioEditIn,
    ScenarioOut,
    ServiceOut,
    StudentResultOut,
)
from app.services import report as report_service
from app.services.ekp import get_ekp
from app.services.generation import DIFFICULTY_LABELS, draft_from_rule, generate_batch
from app.services.response_status import PRIMARY, ResponseStatus

router = APIRouter(prefix="/api/teacher", tags=["Кабинет преподавателя"])


@router.get("/catalog", response_model=CatalogOut)
def catalog(
    db: Session = Depends(get_session), user: User = Depends(require_teacher)
) -> CatalogOut:
    services = db.scalars(select(DispatchService).order_by(DispatchService.name)).all()
    return CatalogOut(
        groups=list(get_ekp().groups),
        services=[ServiceOut.model_validate(s) for s in services],
        difficulties=DIFFICULTY_LABELS,
    )


def _to_out(scenario: Scenario) -> ScenarioOut:
    notified: dict[str, str] = {}
    if scenario.ekp_rule_number:
        try:
            rule = get_ekp().rule(scenario.ekp_rule_number)
            notified = rule.resolve(set(scenario.flags or []))
        except KeyError:
            notified = {}
    return ScenarioOut(
        id=scenario.id,
        title=scenario.title,
        incident_type=scenario.incident_type,
        address=scenario.address,
        description=scenario.description,
        caller=scenario.caller,
        difficulty=scenario.difficulty,
        source=str(scenario.source),
        expected_primary_status=scenario.expected_primary_status,
        is_profile=scenario.is_profile,
        required_comment_points=list(scenario.required_comment_points or []),
        service_name=scenario.target_service.name,
        notified_services=notified,
        approved=scenario.is_approved,
        approved_at=scenario.approved_at,
        teacher_note=scenario.teacher_note,
    )


def _save_draft(db: Session, draft, service: DispatchService, author: User) -> Scenario:
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


@router.post("/scenarios/generate", response_model=GenerateOut)
async def generate(
    payload: GenerateIn,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> GenerateOut:
    service = db.get(DispatchService, payload.service_id)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Служба не найдена")

    drafts = await generate_batch(
        get_llm_provider(),
        group=payload.group,
        count=payload.count,
        service=service.classifier_name,
        difficulty=payload.difficulty,
    )
    scenarios = [_save_draft(db, d, service, user) for d in drafts]
    db.commit()

    warning = None
    if len(scenarios) < payload.count:
        warning = (
            f"Сформировано {len(scenarios)} из {payload.count}: модель ответила "
            "не на все запросы. Повторите генерацию, чтобы добрать недостающие."
        )
    return GenerateOut(
        requested=payload.count,
        created=len(scenarios),
        scenarios=[_to_out(s) for s in scenarios],
        warning=warning,
    )


@router.get("/scenarios", response_model=list[ScenarioOut])
def list_scenarios(
    approved: bool | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> list[ScenarioOut]:
    query = select(Scenario).order_by(Scenario.id.desc())
    if approved is True:
        query = query.where(Scenario.approved_at.is_not(None))
    elif approved is False:
        query = query.where(Scenario.approved_at.is_(None))
    return [_to_out(s) for s in db.scalars(query).all()]


@router.post("/scenarios/{scenario_id}/approve", response_model=ScenarioOut)
def approve(
    scenario_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> ScenarioOut:
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сценарий не найден")
    scenario.approved_by = user
    scenario.approved_at = utcnow()
    db.commit()
    return _to_out(scenario)


@router.post("/scenarios/{scenario_id}/correct", response_model=ScenarioOut)
async def correct(
    scenario_id: int,
    payload: CorrectIn,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> ScenarioOut:
    """Переформирует сценарий с учётом замечания преподавателя.

    Сценарий «Коррекция» из технического задания: преподаватель вводит
    комментарий в контекстное поле, и система отрабатывает его при
    повторном формировании вопроса и эталонного ответа.
    """
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сценарий не найден")
    if scenario.ekp_rule_number is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Сценарий не привязан к классификатору"
        )

    rule = get_ekp().rule(scenario.ekp_rule_number)
    draft = await draft_from_rule(
        get_llm_provider(),
        rule,
        scenario.target_service.classifier_name,
        scenario.difficulty,
        note=payload.note,
    )
    if draft is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Модель недоступна, сценарий не переформирован",
        )

    scenario.description = draft.description
    scenario.address = draft.address
    scenario.caller = draft.caller
    scenario.expected_primary_status = str(draft.expected_primary_status)
    scenario.is_profile = draft.is_profile
    scenario.required_comment_points = list(draft.required_comment_points)
    scenario.teacher_note = payload.note
    # Переформированный сценарий требует повторного утверждения.
    scenario.approved_at = None
    scenario.approved_by = None
    db.commit()
    return _to_out(scenario)


@router.patch("/scenarios/{scenario_id}", response_model=ScenarioOut)
def edit(
    scenario_id: int,
    payload: ScenarioEditIn,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> ScenarioOut:
    """Ручная правка. Эталонный статус меняется вместе с признаком профильности."""
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сценарий не найден")

    data = payload.model_dump(exclude_none=True)
    if "expected_primary_status" in data:
        try:
            target = ResponseStatus(data["expected_primary_status"])
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестный статус"
            ) from None
        if target not in PRIMARY:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Эталоном может быть только «Принята» или «Не принята»",
            )
        scenario.is_profile = target is ResponseStatus.ACCEPTED
        data["expected_primary_status"] = str(target)

    for key, value in data.items():
        setattr(scenario, key, value)
    db.commit()
    return _to_out(scenario)


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    scenario_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> None:
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сценарий не найден")
    if db.scalar(select(Attempt).where(Attempt.scenario_id == scenario_id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Сценарий уже выдавался обучающимся, удалить нельзя",
        )
    db.delete(scenario)
    db.commit()


@router.get("/sessions/{session_id}/report", response_model=ReportOut)
def session_report(
    session_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> ReportOut:
    training = db.get(TrainingSession, session_id)
    if training is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Занятие не найдено")

    attempts = db.scalars(
        select(Attempt).where(Attempt.session_id == session_id)
    ).all()
    data = report_service.build(training, list(attempts))
    return ReportOut(
        session_id=training.id,
        title=training.title,
        state=str(training.state),
        deadline_seconds=training.deadline_seconds,
        started_at=training.started_at,
        finished_at=training.finished_at,
        students=[
            StudentResultOut(
                student_id=s.student_id,
                student_name=s.student_name,
                attempts=s.attempts,
                finished=s.finished,
                average_score=s.average_score,
                overdue=s.overdue,
                violations=dict(s.violations),
            )
            for s in data.students
        ],
        total_attempts=data.total_attempts,
        finished_attempts=data.finished_attempts,
        average_score=data.average_score,
        average_response_seconds=data.average_response_seconds,
        overdue_share=data.overdue_share,
        violations=dict(data.violations),
        grammar_issues=data.grammar_issues,
        insights=data.insights,
    )


@router.get("/sessions", response_model=list[dict])
def list_sessions(
    db: Session = Depends(get_session), user: User = Depends(require_teacher)
) -> list[dict]:
    rows = db.scalars(select(TrainingSession).order_by(TrainingSession.id.desc())).all()
    return [
        {"id": s.id, "title": s.title, "state": str(s.state), "deadline_seconds": s.deadline_seconds}
        for s in rows
    ]
