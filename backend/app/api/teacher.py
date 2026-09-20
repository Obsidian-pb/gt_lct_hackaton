"""Кабинет преподавателя: настройка среды, сценарии, отчёт о занятии."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_teacher
from app.core.db import get_session
from app.llm import get_llm_provider
from app.models.audit import AuditAction
from app.models.base import utcnow
from app.models.training import (
    Attempt,
    Scenario,
    ScenarioSource,
    SessionState,
    TrainingMode,
    TrainingSession,
)
from app.models.user import DispatchService, Role, User
from app.schemas.teacher import (
    CatalogOut,
    MonitorOut,
    ProgressOut,
    CorrectIn,
    GenerateIn,
    GenerateOut,
    ReportOut,
    ScenarioEditIn,
    ScenarioOut,
    ServiceOut,
    SessionIn,
    SessionOut,
    SessionPatch,
    StudentResultOut,
)
from app.services import audit
from app.services import export as export_service
from app.services import report as report_service
from app.services import sessions as session_service
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
        mode=str(scenario.mode),
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
    request: Request,
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
    db.flush()
    audit.record(
        db,
        AuditAction.SCENARIO_GENERATED,
        actor=user,
        object_type="scenario",
        detail={"группа": payload.group, "служба": service.name, "создано": len(scenarios)},
        request=request,
    )
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
    mode: str | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> list[ScenarioOut]:
    query = select(Scenario).order_by(Scenario.id.desc())
    if mode:
        query = query.where(Scenario.mode == TrainingMode(mode))
    if approved is True:
        query = query.where(Scenario.approved_at.is_not(None))
    elif approved is False:
        query = query.where(Scenario.approved_at.is_(None))
    return [_to_out(s) for s in db.scalars(query).all()]


@router.post("/scenarios/{scenario_id}/approve", response_model=ScenarioOut)
def approve(
    scenario_id: int,
    request: Request,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> ScenarioOut:
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сценарий не найден")
    scenario.approved_by = user
    scenario.approved_at = utcnow()
    audit.record(
        db, AuditAction.SCENARIO_APPROVED, actor=user, object_type="scenario",
        object_id=scenario.id, detail={"тип": scenario.incident_type}, request=request,
    )
    db.commit()
    return _to_out(scenario)


@router.post("/scenarios/{scenario_id}/correct", response_model=ScenarioOut)
async def correct(
    scenario_id: int,
    payload: CorrectIn,
    request: Request,
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
    audit.record(
        db, AuditAction.SCENARIO_CORRECTED, actor=user, object_type="scenario",
        object_id=scenario.id, detail={"замечание": payload.note[:200]}, request=request,
    )
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
    request: Request,
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
    audit.record(
        db, AuditAction.SCENARIO_DELETED, actor=user, object_type="scenario",
        object_id=scenario.id, detail={"тип": scenario.incident_type}, request=request,
    )
    db.delete(scenario)
    db.commit()


def _build_report(session_id: int, db: Session) -> report_service.SessionReport:
    """Готовый отчёт по занятию — один источник для экрана и для выгрузок."""
    training = db.get(TrainingSession, session_id)
    if training is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Занятие не найдено")

    attempts = db.scalars(select(Attempt).where(Attempt.session_id == session_id)).all()
    return report_service.build(training, list(attempts))


@router.get("/sessions/{session_id}/report", response_model=ReportOut)
def session_report(
    session_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> ReportOut:
    data = _build_report(session_id, db)
    training = data.session
    return ReportOut(
        session_id=training.id,
        title=training.title,
        state=str(training.state),
        pickup_deadline_seconds=training.pickup_deadline_seconds,
        handling_deadline_seconds=training.handling_deadline_seconds,
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


@router.get("/sessions/{session_id}/report.csv", response_class=Response)
def session_report_csv(
    session_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> Response:
    """Выгрузка отчёта в CSV — для сводной статистики во внешних системах."""
    data = _build_report(session_id, db)
    return Response(
        content=export_service.build_csv(data),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": export_service.content_disposition(data, "csv")
        },
    )


@router.get("/sessions/{session_id}/report.pdf", response_class=Response)
def session_report_pdf(
    session_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> Response:
    """Выгрузка отчёта в PDF — документ для подшивки к занятию."""
    data = _build_report(session_id, db)
    return Response(
        content=export_service.build_pdf(data),
        media_type="application/pdf",
        headers={
            "Content-Disposition": export_service.content_disposition(data, "pdf")
        },
    )


def _session_out(session: TrainingSession) -> SessionOut:
    return SessionOut(
        id=session.id,
        title=session.title,
        mode=str(session.mode),
        state=str(session.state),
        pickup_deadline_seconds=session.pickup_deadline_seconds,
        handling_deadline_seconds=session.handling_deadline_seconds,
        call_interval_seconds=session.call_interval_seconds,
        started_at=session.started_at,
        finished_at=session.finished_at,
        students=[
            {"id": u.id, "full_name": u.full_name, "service": u.service.name if u.service else None}
            for u in session.students
        ],
        scenarios=[
            {"id": s.id, "title": s.title, "approved": s.is_approved} for s in session.scenarios
        ],
        approved_scenarios=sum(1 for s in session.scenarios if s.is_approved),
    )


def _load_session(session_id: int, db: Session) -> TrainingSession:
    session = db.get(TrainingSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Занятие не найдено")
    return session


@router.get("/students", response_model=list[dict])
def students(
    db: Session = Depends(get_session), user: User = Depends(require_teacher)
) -> list[dict]:
    """Обучающиеся, которых можно включить в занятие."""
    rows = db.scalars(
        select(User).where(User.role == Role.STUDENT, User.is_active.is_(True)).order_by(User.full_name)
    ).all()
    return [
        {"id": u.id, "full_name": u.full_name, "service": u.service.name if u.service else None}
        for u in rows
    ]


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    db: Session = Depends(get_session), user: User = Depends(require_teacher)
) -> list[SessionOut]:
    rows = db.scalars(select(TrainingSession).order_by(TrainingSession.id.desc())).all()
    return [_session_out(s) for s in rows]


@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionIn,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> SessionOut:
    session = TrainingSession(
        title=payload.title,
        mode=TrainingMode(payload.mode),
        state=SessionState.DRAFT,
        teacher=user,
        pickup_deadline_seconds=payload.pickup_deadline_seconds,
        handling_deadline_seconds=payload.handling_deadline_seconds,
        call_interval_seconds=payload.call_interval_seconds,
    )
    db.add(session)
    db.commit()
    return _session_out(session)


@router.patch("/sessions/{session_id}", response_model=SessionOut)
def update_session(
    session_id: int,
    payload: SessionPatch,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> SessionOut:
    session = _load_session(session_id, db)
    if session.state is not SessionState.DRAFT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Состав и настройки меняются только до запуска занятия",
        )

    data = payload.model_dump(exclude_unset=True)
    if (ids := data.pop("student_ids", None)) is not None:
        session.students = list(
            db.scalars(select(User).where(User.id.in_(ids), User.role == Role.STUDENT)).all()
        )
    if (ids := data.pop("scenario_ids", None)) is not None:
        chosen = list(db.scalars(select(Scenario).where(Scenario.id.in_(ids))).all())
        # Режимы обучения несовместимы: диспетчер проставляет статусы по готовой
        # карточке, оператор классифицирует вызов. Сценарий чужого режима просто
        # не попал бы в ленту обучающегося и потерялся бы молча.
        foreign = [s for s in chosen if s.mode is not session.mode]
        if foreign:
            names = ", ".join(s.title for s in foreign[:3])
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Сценарии другого режима обучения нельзя включить в это занятие: {names}",
            )
        session.scenarios = chosen
    for key, value in data.items():
        setattr(session, key, value)
    db.commit()
    return _session_out(session)


@router.post("/sessions/{session_id}/start", response_model=SessionOut)
def start_session(
    session_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> SessionOut:
    """Запускает занятие: карточки расходятся по лентам обучающихся."""
    session = _load_session(session_id, db)
    try:
        created = session_service.start(session)
    except session_service.SessionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    db.add_all(created)
    db.commit()
    return _session_out(session)


@router.post("/sessions/{session_id}/finish", response_model=SessionOut)
def finish_session(
    session_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> SessionOut:
    session = _load_session(session_id, db)
    attempts = list(db.scalars(select(Attempt).where(Attempt.session_id == session_id)).all())
    try:
        evaluations = session_service.finish(session, attempts)
    except session_service.SessionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    db.add_all(evaluations)
    db.commit()
    return _session_out(session)


@router.get("/sessions/{session_id}/monitor", response_model=MonitorOut)
def monitor(
    session_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> MonitorOut:
    """Ход занятия прямо сейчас: кто сколько взял и где просрочки."""
    session = _load_session(session_id, db)
    attempts = list(db.scalars(select(Attempt).where(Attempt.session_id == session_id)).all())
    rows = session_service.progress(session, attempts)
    return MonitorOut(
        session_id=session.id,
        state=str(session.state),
        started_at=session.started_at,
        call_interval_seconds=session.call_interval_seconds,
        pickup_deadline_seconds=session.pickup_deadline_seconds,
        total_planned=len(attempts),
        issued=sum(r.issued for r in rows),
        finished=sum(r.finished for r in rows),
        students=[ProgressOut(**vars(r)) for r in rows],
    )
