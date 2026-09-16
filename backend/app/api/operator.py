"""Рабочее место оператора Службы 112: приём вызова и заполнение карточки."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.attempts import run_llm_review
from app.api.deps import get_current_user
from app.core.db import get_session
from app.models.base import as_utc, utcnow
from app.models.training import Attempt, Evaluation, Scenario, TrainingMode
from app.models.user import Role, User
from app.services.ekp import get_ekp
from app.services.operator import DEFAULT_CALL_DEADLINE_SECONDS, FilledCard
from app.services.operator import evaluate as evaluate_card
from app.services.survey import options_at, survey_tree

router = APIRouter(prefix="/api/operator", tags=["Рабочее место оператора 112"])


class OptionOut(BaseModel):
    label: str
    has_children: bool
    is_final: bool
    incident_type: str | None = None


class CallOut(BaseModel):
    """Вызов глазами оператора: он слышит заявителя, но карточки ещё нет."""

    attempt_id: int
    legend: str
    reported_address: str
    caller: str
    issued_at: str
    deadline_seconds: int
    elapsed_seconds: float
    finished: bool
    chosen_group: str | None
    chosen_path: list[str]
    entered_address: str | None
    entered_description: str | None


class ClassifyIn(BaseModel):
    group: str
    path: list[str] = Field(default_factory=list)
    address: str = ""
    description: str = ""


class ClassificationOut(BaseModel):
    correct: bool
    chosen_incident_type: str | None
    expected_incident_type: str
    matched_depth: int
    expected_depth: int
    missed_services: list[str]
    extra_services: list[str]
    notified_services: dict[str, str]


class OperatorEvaluationOut(BaseModel):
    attempt_id: int
    score: float
    violations: list[dict]
    classification: ClassificationOut | None
    llm_pending: bool
    llm_available: bool
    llm_summary: str | None = None
    grammar_issues: list[str] = Field(default_factory=list)


def _load(attempt_id: int, db: Session, user: User) -> Attempt:
    attempt = db.get(Attempt, attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вызов не найден")
    if user.role is Role.STUDENT and attempt.student_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к этому вызову")
    if attempt.scenario.mode is not TrainingMode.OPERATOR:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Этот сценарий относится к режиму диспетчера ДДС"
        )
    return attempt


def _call(attempt: Attempt) -> CallOut:
    reference = as_utc(attempt.finished_at) if attempt.finished_at else utcnow()
    return CallOut(
        attempt_id=attempt.id,
        legend=attempt.scenario.description,
        reported_address=attempt.scenario.address,
        caller=attempt.scenario.caller,
        issued_at=as_utc(attempt.issued_at).isoformat(),
        deadline_seconds=attempt.scenario.deadline_seconds or DEFAULT_CALL_DEADLINE_SECONDS,
        elapsed_seconds=(reference - as_utc(attempt.issued_at)).total_seconds(),
        finished=attempt.finished_at is not None,
        chosen_group=attempt.chosen_group,
        chosen_path=list(attempt.chosen_path or []),
        entered_address=attempt.entered_address,
        entered_description=attempt.entered_description,
    )


@router.get("/groups", response_model=list[str])
def groups(user: User = Depends(get_current_user)) -> list[str]:
    """Категории происшествий верхнего уровня опросной карты."""
    return sorted(survey_tree())


@router.get("/options", response_model=list[OptionOut])
def options(
    group: str,
    path: str = "",
    user: User = Depends(get_current_user),
) -> list[OptionOut]:
    """Признаки, доступные на текущем шаге. Путь передаётся через «|»."""
    selected = [p for p in path.split("|") if p]
    return [OptionOut(**o) for o in options_at(group, selected)]


@router.get("/calls/my", response_model=list[CallOut])
def my_calls(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> list[CallOut]:
    rows = db.scalars(
        select(Attempt)
        .join(Scenario)
        .where(
            Attempt.student_id == user.id,
            Scenario.mode == TrainingMode.OPERATOR,
            Attempt.issued_at <= utcnow(),
        )
        .order_by(Attempt.id)
    ).all()
    return [_call(a) for a in rows]


@router.get("/calls/{attempt_id}", response_model=CallOut)
def get_call(
    attempt_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CallOut:
    return _call(_load(attempt_id, db, user))


@router.post("/calls/{attempt_id}/classify", response_model=OperatorEvaluationOut)
def classify_call(
    attempt_id: int,
    payload: ClassifyIn,
    background: BackgroundTasks,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> OperatorEvaluationOut:
    """Сохраняет заполненную карточку и сразу выдаёт разбор.

    Оценка классификации полностью детерминирована — эталон задан строкой
    классификатора. Языковой модели остаётся только грамматика описания,
    и она догружается фоном.
    """
    attempt = _load(attempt_id, db, user)
    if attempt.finished_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Вызов уже обработан")

    scenario = attempt.scenario
    if scenario.ekp_rule_number is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Сценарий не привязан к классификатору"
        )

    now = utcnow()
    attempt.chosen_group = payload.group or None
    attempt.chosen_path = list(payload.path)
    attempt.entered_address = payload.address.strip() or None
    attempt.entered_description = payload.description.strip() or None
    attempt.finished_at = now

    deadline = scenario.deadline_seconds or DEFAULT_CALL_DEADLINE_SECONDS
    assessment = evaluate_card(
        FilledCard(
            group=payload.group or None,
            path=tuple(payload.path),
            address=payload.address,
            description=payload.description,
            elapsed_seconds=(now - as_utc(attempt.issued_at)).total_seconds(),
        ),
        scenario.ekp_rule_number,
        deadline,
    )

    evaluation = Evaluation(
        attempt=attempt,
        score=assessment.score,
        criteria={},
        violations=[
            {
                "code": v.code,
                "title": v.kind.title,
                "criterion": str(v.kind.criterion),
                "severity": str(v.kind.severity),
                "detail": v.detail,
                "evidence": v.evidence,
                "example": v.kind.example,
            }
            for v in assessment.violations
        ],
        # Модель нужна только для грамматики описания.
        llm_pending=bool(attempt.entered_description),
    )
    db.add(evaluation)
    db.commit()

    if evaluation.llm_pending:
        background.add_task(run_llm_review, attempt.id)

    return _out(attempt, evaluation, assessment)


def _out(attempt: Attempt, evaluation: Evaluation, assessment) -> OperatorEvaluationOut:
    classification = None
    if assessment.classification is not None:
        result = assessment.classification
        chosen = result.chosen_rule
        classification = ClassificationOut(
            correct=result.correct,
            chosen_incident_type=chosen.incident_type if chosen else None,
            expected_incident_type=result.expected_rule.incident_type,
            matched_depth=result.matched_depth,
            expected_depth=result.expected_depth,
            missed_services=list(result.missed_services),
            extra_services=list(result.extra_services),
            notified_services=get_ekp().rule(result.expected_rule.number).resolve(),
        )
    return OperatorEvaluationOut(
        attempt_id=attempt.id,
        score=evaluation.score,
        violations=list(evaluation.violations),
        classification=classification,
        llm_pending=evaluation.llm_pending,
        llm_available=evaluation.llm_available,
        llm_summary=evaluation.llm_summary,
        grammar_issues=list(evaluation.grammar_issues or []),
    )
