from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import forbid_admin_to_student_work, get_current_user
from app.core.db import SessionLocal, get_session
from app.llm import get_llm_provider
from app.models.base import as_utc, utcnow
from app.models.training import Attempt, Evaluation, Scenario, TrainingMode
from app.models.user import Role, User
from app.schemas.training import CardOut, EvaluationOut, StatusIn
from app.services import attempts as service
from app.services import sessions as session_service
from app.services.classifier_versions import ekp_for_session
from app.services.response_status import COMMENT_REQUIRED, ResponseStatus

router = APIRouter(prefix="/api/attempts", tags=["Работа на АРМ-112"])


def complete_attempt(
    db: Session, attempt: Attempt, evaluation: Evaluation, background: BackgroundTasks
) -> Attempt | None:
    """Общее завершение попытки в обоих режимах обучения.

    Сохраняет детерминированную оценку, при провале назначает повторную
    выдачу той же карточки и только потом запускает языковую модель.
    Порядок важен: повтор не должен ждать модели — её ответ может прийти
    через минуту, а может не прийти вовсе, и карточка тогда не вернулась бы.

    Возвращает назначенный повтор, если он создан.
    """
    db.add(evaluation)
    # Все выдачи обучающегося в этом занятии: повтор встаёт после последней.
    planned = db.scalars(
        select(Attempt).where(
            Attempt.session_id == attempt.session_id,
            Attempt.student_id == attempt.student_id,
        )
    ).all()
    repeat = session_service.schedule_repeat(attempt, evaluation, list(planned))
    if repeat is not None:
        db.add(repeat)
    db.commit()

    # Детерминированная оценка уже готова и отдаётся сразу — норматив отклика
    # в 2 секунды не зависит от скорости работы LLM.
    if evaluation.llm_pending:
        background.add_task(run_llm_review, attempt.id)
    return repeat


def _load(attempt_id: int, db: Session, user: User) -> Attempt:
    attempt = db.get(Attempt, attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Карточка не найдена")
    # Обучающийся не должен видеть работу других обучающихся.
    if user.role is Role.STUDENT and attempt.student_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к этой карточке")
    forbid_admin_to_student_work(user)
    return attempt


def _card(attempt: Attempt) -> CardOut:
    scenario = attempt.scenario
    notified: dict[str, str] = {}
    if scenario.ekp_rule_number:
        # Список оповещения — по редакции классификатора, по которой идёт
        # занятие: карточка обязана выглядеть так же и через год.
        ekp = ekp_for_session(attempt.session)
        try:
            notified = ekp.rule(scenario.ekp_rule_number).resolve(set(scenario.flags or []))
        except KeyError:
            notified = {}

    current = service.current_status(attempt)
    pickup, handling = service.timings(attempt)
    reference = as_utc(attempt.finished_at) if attempt.finished_at else utcnow()
    return CardOut(
        attempt_id=attempt.id,
        incident_type=scenario.incident_type,
        address=scenario.address,
        description=scenario.description,
        caller=scenario.caller,
        notified_services=notified,
        issued_at=attempt.issued_at,
        opened_at=attempt.opened_at,
        pickup_deadline_seconds=attempt.session.pickup_deadline_seconds,
        handling_deadline_seconds=attempt.session.handling_deadline_seconds,
        elapsed_seconds=(reference - as_utc(attempt.issued_at)).total_seconds(),
        pickup_seconds=pickup,
        handling_seconds=handling,
        current_status=str(current) if current else None,
        available_statuses=[str(s) for s in service.available_statuses(attempt)],
        comment_required_for=[str(s) for s in COMMENT_REQUIRED],
        card_status=str(attempt.card_status),
        finished=attempt.finished_at is not None,
        is_repeat=attempt.repeat_of_id is not None,
    )


@router.get("/my", response_model=list[CardOut])
def my_cards(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> list[CardOut]:
    # Вызовы оператора живут в отдельной ленте: там другая задача и другой
    # интерфейс, смешивать их с карточками диспетчера нельзя.
    rows = db.scalars(
        select(Attempt)
        .join(Scenario)
        .where(
            Attempt.student_id == user.id,
            Scenario.mode == TrainingMode.DISPATCHER,
            # Вызовы приходят потоком: карточка появляется в ленте, когда
            # наступает её время, а не в начале занятия.
            Attempt.issued_at <= utcnow(),
        )
        .order_by(Attempt.issued_at.desc())
    ).all()
    return [_card(a) for a in rows]


@router.get("/{attempt_id}", response_model=CardOut)
def get_card(
    attempt_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CardOut:
    return _card(_load(attempt_id, db, user))


@router.post("/{attempt_id}/open", response_model=CardOut)
def open_card(
    attempt_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CardOut:
    attempt = service.open_card(_load(attempt_id, db, user))
    db.commit()
    return _card(attempt)


@router.post("/{attempt_id}/status", response_model=CardOut)
def set_status(
    attempt_id: int,
    payload: StatusIn,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CardOut:
    attempt = _load(attempt_id, db, user)
    try:
        target = ResponseStatus(payload.status)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Неизвестный статус «{payload.status}»"
        ) from None
    try:
        service.record_status(attempt, target, payload.comment)
    except service.AttemptError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    db.commit()
    return _card(attempt)


@router.post("/{attempt_id}/finish", response_model=EvaluationOut)
def finish(
    attempt_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> EvaluationOut:
    attempt = _load(attempt_id, db, user)
    if attempt.evaluation is not None:
        return _evaluation_out(attempt.evaluation)

    service.finish(attempt)
    evaluation = service.build_evaluation(attempt)
    complete_attempt(db, attempt, evaluation, background)
    return _evaluation_out(evaluation)


@router.get("/{attempt_id}/evaluation", response_model=EvaluationOut)
def get_evaluation(
    attempt_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> EvaluationOut:
    attempt = _load(attempt_id, db, user)
    if attempt.evaluation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Оценка ещё не сформирована")
    return _evaluation_out(attempt.evaluation)


def _evaluation_out(evaluation: Evaluation) -> EvaluationOut:
    return EvaluationOut(
        attempt_id=evaluation.attempt_id,
        score=evaluation.score,
        criteria=evaluation.criteria,
        violations=evaluation.violations,
        llm_pending=evaluation.llm_pending,
        llm_available=evaluation.llm_available,
        llm_summary=evaluation.llm_summary,
        grammar_issues=evaluation.grammar_issues or [],
        teacher_feedback=evaluation.teacher_feedback,
        teacher_feedback_at=evaluation.teacher_feedback_at,
        teacher_feedback_by=(
            evaluation.teacher_feedback_by.full_name
            if evaluation.teacher_feedback_by
            else None
        ),
    )


async def run_llm_review(attempt_id: int) -> None:
    """Фоновая смысловая проверка комментариев.

    Выполняется после ответа клиенту. Недоступность провайдера не влияет
    на уже выставленную детерминированную оценку — фиксируется признаком
    llm_available.
    """
    from app.services.violations import CATALOG

    with SessionLocal() as db:
        attempt = db.get(Attempt, attempt_id)
        if attempt is None or attempt.evaluation is None:
            return
        # Идемпотентность: повторный запуск не должен дублировать нарушения.
        if not attempt.evaluation.llm_pending:
            return

        if attempt.scenario.mode is TrainingMode.OPERATOR:
            # У оператора нет комментариев к статусам: он вносит описание
            # происшествия, и проверять нужно именно его грамматику.
            text = attempt.entered_description or ""
            required: list[str] = []
        else:
            text = "\n".join(e.comment for e in attempt.events if e.comment)
            required = list(attempt.scenario.required_comment_points or [])

        review = await get_llm_provider().review_comment(
            comment=text,
            required_points=required,
            context=f"{attempt.scenario.incident_type}. {attempt.scenario.description}",
        )

        evaluation = attempt.evaluation
        kind = CATALOG["V5"]
        extra = [
            {
                "code": kind.code,
                "title": kind.title,
                "criterion": str(kind.criterion),
                "severity": str(kind.severity),
                "detail": f"В комментарии не отражено: {point}",
                "evidence": None,
                "example": kind.example,
            }
            for point in review.missing_points
        ]
        evaluation.violations = list(evaluation.violations) + extra
        evaluation.score = max(0.0, evaluation.score - 0.5 * len(extra) / 3.0)
        evaluation.grammar_issues = review.grammar_issues
        evaluation.llm_available = review.available
        # Недоступность модели нельзя выдавать за отсутствие замечаний: без
        # этой пометки обучающийся получил бы завышенный балл, а преподаватель
        # увидел бы «нарушений нет» вместо «проверка не выполнена».
        evaluation.llm_summary = (
            review.summary
            if review.available
            else "Смысловая проверка комментариев не выполнена: модель недоступна. "
            "Оценка учитывает только норматив, статусы и наличие комментариев."
        )
        evaluation.llm_pending = False
        db.commit()
