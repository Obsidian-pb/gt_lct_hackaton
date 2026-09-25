"""Кабинет преподавателя: настройка среды, сценарии, отчёт о занятии."""

from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_teacher
from app.core.db import get_session
from app.llm import get_llm_provider
from app.models.audit import AuditAction
from app.models.base import utcnow
from app.models.training import (
    StudyGroup,
    Attempt,
    Evaluation,
    Scenario,
    ScenarioSource,
    SessionState,
    TrainingMode,
    TrainingSession,
    GenerationJob,
    GenerationState,
)
from app.models.user import DispatchService, Role, User
from app.schemas.teacher import (
    GroupIn,
    GroupOut,
    GroupPatch,
    CatalogOut,
    MonitorOut,
    ProgressOut,
    CorrectIn,
    DashboardOut,
    DashboardSessionOut,
    DashboardWorkOut,
    FeedbackIn,
    GenerateIn,
    GenerationJobOut,
    GrammarCheckOut,
    RepeatResultOut,
    ReportOut,
    ScenarioEditIn,
    ScenarioOut,
    ServiceOut,
    SessionIn,
    SessionOut,
    SessionPatch,
    StudentResultOut,
    WorkOut,
)
from app.services import audit
from app.services import export as export_service
from app.services import report as report_service
from app.services import sessions as session_service
from app.services.flags import known_keys
from app.services import generation_jobs
from app.services.classifier_versions import active_version, current_ekp
from app.services.ekp import EKP
from app.services.generation import DIFFICULTY_LABELS, draft_from_rule
from app.services.response_status import PRIMARY, ResponseStatus

router = APIRouter(prefix="/api/teacher", tags=["Кабинет преподавателя"])


@router.get("/catalog", response_model=CatalogOut)
def catalog(
    db: Session = Depends(get_session), user: User = Depends(require_teacher)
) -> CatalogOut:
    services = db.scalars(select(DispatchService).order_by(DispatchService.name)).all()
    # Группы — из действующей редакции классификатора: сценарий готовится
    # к будущим занятиям, а они будут привязаны к ней.
    return CatalogOut(
        groups=list(current_ekp(db).groups),
        services=[ServiceOut.model_validate(s) for s in services],
        difficulties=DIFFICULTY_LABELS,
    )


def _to_out(scenario: Scenario, ekp: EKP) -> ScenarioOut:
    """Сценарий для кабинета. Список оповещения — по переданной редакции.

    У сценария нет своего занятия, поэтому редакцию выбирает вызывающий:
    в кабинете это действующая. Правило, которого в ней нет, оставляет
    список пустым, а не роняет весь список сценариев.
    """
    notified: dict[str, str] = {}
    if scenario.ekp_rule_number:
        try:
            rule = ekp.rule(scenario.ekp_rule_number)
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
        flags=list(scenario.flags or []),
        source=str(scenario.source),
        expected_primary_status=scenario.expected_primary_status,
        expected_outcome=str(scenario.expected_outcome),
        referral_target=scenario.referral_target,
        is_profile=scenario.is_profile,
        required_comment_points=list(scenario.required_comment_points or []),
        service_name=scenario.target_service.name,
        notified_services=notified,
        approved=scenario.is_approved,
        approved_at=scenario.approved_at,
        teacher_note=scenario.teacher_note,
    )


def _job_out(job: GenerationJob) -> GenerationJobOut:
    warning = None
    if job.state is GenerationState.DONE and job.created < job.requested:
        warning = (
            f"Сформировано {job.created} из {job.requested}: модель ответила "
            "не на все запросы. Повторите формирование, чтобы добрать недостающие."
        )
    return GenerationJobOut(
        id=job.id,
        state=str(job.state),
        group=job.group,
        service_name=job.service.name,
        requested=job.requested,
        finished=job.finished,
        created=job.created,
        scenario_ids=list(job.scenario_ids or []),
        error=job.error,
        started_at=job.created_at,
        finished_at=job.finished_at,
        warning=warning,
    )


@router.post(
    "/scenarios/generate",
    response_model=GenerationJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate(
    payload: GenerateIn,
    background: BackgroundTasks,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> GenerationJobOut:
    """Запускает формирование карточек в фоне и сразу возвращает задание.

    Модель на процессоре пишет карточку около минуты; держать запрос
    открытым на пять карточек нельзя. Готовые появляются в списке по одной,
    ход виден по GET /scenarios/generate/{id}.
    """
    service = db.get(DispatchService, payload.service_id)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Служба не найдена")
    job = generation_jobs.start(
        db,
        teacher=user,
        group=payload.group,
        count=payload.count,
        difficulty=payload.difficulty,
        service=service,
    )
    background.add_task(generation_jobs.run, job.id)
    return _job_out(job)


@router.get("/scenarios/generate/active", response_model=list[GenerationJobOut])
def active_generations(
    db: Session = Depends(get_session), user: User = Depends(require_teacher)
) -> list[GenerationJobOut]:
    return [_job_out(j) for j in generation_jobs.active_for(db, user)]


@router.get("/scenarios/generate/{job_id}", response_model=GenerationJobOut)
def generation_status(
    job_id: int, db: Session = Depends(get_session), user: User = Depends(require_teacher)
) -> GenerationJobOut:
    job = db.get(GenerationJob, job_id)
    if job is None or job.teacher_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание не найдено")
    return _job_out(job)


@router.get("/scenarios", response_model=list[ScenarioOut])
def list_scenarios(
    approved: bool | None = None,
    mode: str | None = None,
    difficulty: int | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> list[ScenarioOut]:
    query = select(Scenario).order_by(Scenario.id.desc())
    if mode:
        query = query.where(Scenario.mode == TrainingMode(mode))
    # Отбор по уровню сложности: преподаватель собирает состав занятия
    # из заданий нужного уровня, а не перебирает весь список глазами.
    if difficulty is not None:
        query = query.where(Scenario.difficulty == difficulty)
    if approved is True:
        query = query.where(Scenario.approved_at.is_not(None))
    elif approved is False:
        query = query.where(Scenario.approved_at.is_(None))
    ekp = current_ekp(db)
    return [_to_out(s, ekp) for s in db.scalars(query).all()]


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
    return _to_out(scenario, current_ekp(db))


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

    ekp = current_ekp(db)
    try:
        rule = ekp.rule(scenario.ekp_rule_number)
    except KeyError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Правила № {scenario.ekp_rule_number} нет в действующей редакции "
            "классификатора: сценарий составлен по прежней редакции",
        ) from None
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
    return _to_out(scenario, ekp)


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

    if "flags" in data:
        # Ключи признаков — из классификатора: опечатка в признаке молча
        # выключила бы сверку, а не дала бы ошибку.
        unknown = sorted(set(data["flags"]) - known_keys(current_ekp(db)))
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Неизвестные признаки: " + ", ".join(unknown),
            )
        data["flags"] = list(dict.fromkeys(data["flags"]))

    for key, value in data.items():
        setattr(scenario, key, value)
    db.commit()
    return _to_out(scenario, current_ekp(db))


# Поля, которые преподаватель правит руками и которые имеет смысл проверять:
# заявителя и служебные отметки в проверку не берём — там имена и телефоны,
# на них модель выдаёт замечания к каждому слову.
GRAMMAR_FIELDS = ("Название", "Адрес", "Описание", "Обязательные пункты комментария")


@router.post("/scenarios/{scenario_id}/grammar", response_model=GrammarCheckOut)
async def check_grammar(
    scenario_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> GrammarCheckOut:
    """Принудительная проверка грамматики текста сценария.

    Сценарий подготовки занятия из технического задания: после ручных
    правок преподаватель по своей команде проверяет написанное. Проверка
    ничего в сценарии не меняет — она только возвращает замечания, решение
    остаётся за преподавателем.

    Отдельного метода у провайдера нет и не нужно: review_comment уже
    возвращает grammar_issues, а список обязательных пунктов при пустом
    значении не даёт замечаний по существу.
    """
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сценарий не найден")

    text = "\n".join(
        part
        for part in (
            scenario.title,
            scenario.address,
            scenario.description,
            *(scenario.required_comment_points or []),
        )
        if part
    )
    review = await get_llm_provider().review_comment(
        comment=text,
        required_points=[],
        context=scenario.incident_type,
    )
    if not review.available:
        # Молчание здесь читалось бы как «ошибок нет», а это неправда:
        # проверка не выполнена вовсе.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Модель недоступна, проверка грамматики не выполнена. "
            "Текст сценария не изменён.",
        )
    return GrammarCheckOut(
        scenario_id=scenario.id,
        issues=review.grammar_issues,
        checked_fields=list(GRAMMAR_FIELDS),
    )


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
                critical=s.critical,
                passed=s.passed(data.pass_score, data.max_critical_violations),
                repeats=[RepeatResultOut(**vars(r)) for r in s.repeats],
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
        pass_score=data.pass_score,
        max_critical_violations=data.max_critical_violations,
        passed_students=data.passed_students,
        failed_students=data.failed_students,
        repeats_issued=data.repeats_issued,
        repeats_finished=data.repeats_finished,
        repeats_fixed=data.repeats_fixed,
    )


def _work_out(attempt: Attempt) -> WorkOut:
    evaluation = attempt.evaluation
    critical = report_service.critical_violations(
        evaluation.violations if evaluation else []
    )
    return WorkOut(
        attempt_id=attempt.id,
        student_id=attempt.student_id,
        student_name=attempt.student.full_name,
        scenario_title=attempt.scenario.title,
        finished_at=attempt.finished_at,
        score=evaluation.score if evaluation else None,
        violations=len(evaluation.violations or []) if evaluation else 0,
        critical=critical,
        teacher_feedback=evaluation.teacher_feedback if evaluation else None,
        teacher_feedback_at=evaluation.teacher_feedback_at if evaluation else None,
        teacher_feedback_by=(
            evaluation.teacher_feedback_by.full_name
            if evaluation and evaluation.teacher_feedback_by
            else None
        ),
        repeat_of_id=attempt.repeat_of_id,
    )


@router.get("/sessions/{session_id}/works", response_model=list[WorkOut])
def session_works(
    session_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> list[WorkOut]:
    """Работы занятия поимённо — отсюда преподаватель даёт обратную связь.

    Отчёт сводит результаты по обучающемуся, а комментировать техническое
    задание требует конкретную работу, поэтому список отдельный.
    """
    _load_session(session_id, db)
    attempts = db.scalars(
        select(Attempt).where(Attempt.session_id == session_id).order_by(Attempt.id)
    ).all()
    return [_work_out(a) for a in attempts]


@router.post("/attempts/{attempt_id}/feedback", response_model=WorkOut)
def leave_feedback(
    attempt_id: int,
    payload: FeedbackIn,
    request: Request,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> WorkOut:
    """Примечание преподавателя к конкретной работе обучающегося.

    Требование технического задания о предоставлении обратной связи
    через интерфейс системы. Автор и время сохраняются рядом с текстом:
    примечание дописывается к уже выставленной оценке, а результаты
    обучения нельзя менять без фиксации в журнале аудита.
    """
    attempt = db.get(Attempt, attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Работа не найдена")

    evaluation: Evaluation | None = attempt.evaluation
    if evaluation is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Работа ещё не завершена: комментировать нечего",
        )

    evaluation.teacher_feedback = payload.text
    evaluation.teacher_feedback_at = utcnow()
    evaluation.teacher_feedback_by = user
    audit.record(
        db, AuditAction.FEEDBACK_LEFT, actor=user, object_type="attempt",
        object_id=attempt.id,
        detail={"обучающийся": attempt.student.full_name, "примечание": payload.text[:200]},
        request=request,
    )
    db.commit()
    return _work_out(attempt)


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
        pass_score=session.pass_score,
        max_critical_violations=session.max_critical_violations,
        repeat_failed=session.repeat_failed,
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
        classifier_version_label=(
            session.classifier_version.label if session.classifier_version else None
        ),
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


def _group_out(group: StudyGroup) -> GroupOut:
    return GroupOut(
        id=group.id,
        title=group.title,
        note=group.note,
        teacher_name=group.teacher.full_name,
        students=[
            {"id": u.id, "full_name": u.full_name, "service": u.service.name if u.service else None}
            for u in sorted(group.students, key=lambda u: u.full_name)
        ],
    )


def _students_by_ids(db: Session, ids: list[int]) -> list[User]:
    """Только действующие обучающиеся: заблокированного включать в группу незачем."""
    return list(
        db.scalars(
            select(User).where(
                User.id.in_(ids), User.role == Role.STUDENT, User.is_active.is_(True)
            )
        ).all()
    )


@router.get("/groups", response_model=list[GroupOut])
def list_groups(
    db: Session = Depends(get_session), user: User = Depends(require_teacher)
) -> list[GroupOut]:
    """Учебные группы видны всем преподавателям: смену ведёт тот, кто на месте."""
    rows = db.scalars(select(StudyGroup).order_by(StudyGroup.title)).all()
    return [_group_out(g) for g in rows]


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: GroupIn,
    request: Request,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> GroupOut:
    if db.scalar(select(StudyGroup).where(StudyGroup.title == payload.title)):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Группа «{payload.title}» уже заведена"
        )
    group = StudyGroup(
        title=payload.title,
        note=payload.note,
        teacher=user,
        students=_students_by_ids(db, payload.student_ids),
    )
    db.add(group)
    db.flush()
    audit.record(
        db,
        AuditAction.GROUP_CREATED,
        actor=user,
        object_type="group",
        object_id=group.id,
        detail={"title": group.title, "students": len(group.students)},
        request=request,
    )
    db.commit()
    return _group_out(group)


@router.patch("/groups/{group_id}", response_model=GroupOut)
def update_group(
    group_id: int,
    payload: GroupPatch,
    request: Request,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> GroupOut:
    group = db.get(StudyGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Группа не найдена")

    data = payload.model_dump(exclude_unset=True)
    if (ids := data.pop("student_ids", None)) is not None:
        group.students = _students_by_ids(db, ids)
    for key, value in data.items():
        setattr(group, key, value)
    audit.record(
        db,
        AuditAction.GROUP_UPDATED,
        actor=user,
        object_type="group",
        object_id=group.id,
        detail={"fields": sorted(payload.model_dump(exclude_unset=True))},
        request=request,
    )
    db.commit()
    return _group_out(group)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: int,
    request: Request,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> None:
    group = db.get(StudyGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Группа не найдена")
    # Проведённые занятия не пострадают: состав копировался в занятие,
    # а не ссылался на группу.
    audit.record(
        db,
        AuditAction.GROUP_DELETED,
        actor=user,
        object_type="group",
        object_id=group.id,
        detail={"title": group.title},
        request=request,
    )
    db.delete(group)
    db.commit()


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
        pass_score=payload.pass_score,
        max_critical_violations=payload.max_critical_violations,
        repeat_failed=payload.repeat_failed,
        # Редакция классификатора фиксируется при создании: смена действующей
        # редакции после этого занятие не затрагивает. Пусто — встроенная.
        classifier_version=active_version(db),
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
    if (group_id := data.pop("group_id", None)) is not None:
        group = db.get(StudyGroup, group_id)
        if group is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Группа не найдена")
        # Состав копируется, а не связывается ссылкой: занятие — это событие,
        # и правка группы через неделю не должна переписывать его состав.
        session.students = list(group.students)
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
    issued, finished = _progress_totals(rows)
    return MonitorOut(
        session_id=session.id,
        state=str(session.state),
        started_at=session.started_at,
        call_interval_seconds=session.call_interval_seconds,
        pickup_deadline_seconds=session.pickup_deadline_seconds,
        total_planned=len(attempts),
        issued=issued,
        finished=finished,
        students=[ProgressOut(**vars(r)) for r in rows],
    )


def _progress_totals(rows: list[session_service.StudentProgress]) -> tuple[int, int]:
    """Поступило и обработано по занятию в целом — сумма по обучающимся.

    Общая для монитора и главной страницы: цифра «поступило» на сводке
    обязана совпадать с той, что преподаватель увидит, открыв занятие.
    """
    return sum(r.issued for r in rows), sum(r.finished for r in rows)


# Горизонт сводки на главной. Неделя — обычный цикл занятий группы: за неё
# видно, как прошла последняя серия, и не тонут занятия прошлого месяца.
DASHBOARD_DAYS = 7
DASHBOARD_SESSIONS = 5
DASHBOARD_WORKS = 8


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    db: Session = Depends(get_session), user: User = Depends(require_teacher)
) -> DashboardOut:
    """Сводка для главной страницы преподавателя.

    Отвечает на два вопроса при входе: что идёт прямо сейчас и что ждёт
    его действий — сценарии без утверждения и работы без примечания.
    Только чтение: сводка ничего не меняет и ничего не запускает.
    """

    def count(model, *where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    since = utcnow() - timedelta(days=DASHBOARD_DAYS)
    # Работа завершена, когда по ней есть оценка: карточку, закрытую
    # по окончании занятия без действий обучающегося, finish тоже оценивает,
    # и она здесь считается — до неё обучающийся не добрался, это результат.
    completed = (
        select(Attempt)
        .join(Evaluation, Evaluation.attempt_id == Attempt.id)
        .where(Attempt.finished_at.is_not(None))
        .order_by(Attempt.finished_at.desc(), Attempt.id.desc())
    )
    finished = db.scalars(completed.where(Attempt.finished_at >= since)).all()
    # Лента последних работ — без горизонта: после перерыва в занятиях
    # преподаватель всё равно должен видеть, на чём остановился.
    recent = db.scalars(completed.limit(DASHBOARD_WORKS)).all()
    # Средний балл и доля зачтённых — по первым попыткам, как в отчёте
    # занятия: повтор в средний балл первого прохода не входит.
    first = [a for a in finished if a.repeat_of_id is None]
    passed = sum(
        1
        for a in first
        if not report_service.attempt_failed(a.evaluation, a.session.pass_score)
    )

    active = db.scalars(
        select(TrainingSession)
        .where(TrainingSession.state == SessionState.ACTIVE)
        .order_by(TrainingSession.started_at.desc(), TrainingSession.id.desc())
        .limit(DASHBOARD_SESSIONS)
    ).all()
    sessions: list[DashboardSessionOut] = []
    for session in active:
        attempts = list(
            db.scalars(select(Attempt).where(Attempt.session_id == session.id)).all()
        )
        issued, done = _progress_totals(session_service.progress(session, attempts))
        sessions.append(
            DashboardSessionOut(
                id=session.id,
                title=session.title,
                mode=str(session.mode),
                students=len(session.students),
                issued=issued,
                finished=done,
            )
        )

    return DashboardOut(
        active_sessions=count(TrainingSession, TrainingSession.state == SessionState.ACTIVE),
        students_total=count(User, User.role == Role.STUDENT, User.is_active.is_(True)),
        scenarios_pending=count(Scenario, Scenario.approved_at.is_(None)),
        groups_total=count(StudyGroup),
        works_7d=len(finished),
        average_score_7d=(
            round(sum(a.evaluation.score for a in first) / len(first), 3) if first else None
        ),
        passed_share_7d=round(passed / len(first), 3) if first else None,
        feedback_missing=sum(1 for a in finished if not a.evaluation.teacher_feedback),
        sessions=sessions,
        recent_works=[
            DashboardWorkOut(
                attempt_id=a.id,
                student_name=a.student.full_name,
                scenario_title=a.scenario.title,
                session_id=a.session_id,
                session_title=a.session.title,
                score=a.evaluation.score,
                critical=report_service.critical_violations(a.evaluation.violations),
                finished_at=a.finished_at,
                has_feedback=bool(a.evaluation.teacher_feedback),
            )
            for a in recent
        ],
    )
