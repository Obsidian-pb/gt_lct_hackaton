"""Рабочее место оператора Службы 112: приём вызова и заполнение карточки."""

import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.attempts import complete_attempt
from app.api.deps import forbid_admin_to_student_work, get_current_user
from app.core.db import get_session
from app.models.base import as_utc, utcnow
from app.models.training import (
    Attempt,
    CallOutcome,
    Evaluation,
    Scenario,
    ScenarioSource,
    TrainingMode,
)
from app.models.user import Role, User
from app.schemas.training import NotificationReasonOut
from app.services import flags as flag_titles
from app.services.classifier_versions import current_ekp, ekp_for_session
from app.services.ekp import EKP
from app.services.operator import DEFAULT_CALL_DEADLINE_SECONDS, Expected, FilledCard
from app.services.operator import evaluate as evaluate_card
from app.services.survey import options_at, resolve, survey_tree

router = APIRouter(prefix="/api/operator", tags=["Рабочее место оператора 112"])


class OptionOut(BaseModel):
    label: str
    has_children: bool
    is_final: bool
    incident_type: str | None = None


class FlagOut(BaseModel):
    """Кнопка признака на карточке: ключ для запроса и подпись для оператора."""

    key: str
    title: str
    hint: str


class FlagsOut(BaseModel):
    # Три кнопки, которые на карточке АРМ-112 есть всегда. Имя поля
    # в ответе — `global`, как в контракте; в Python оно зарезервировано.
    global_: list[FlagOut] = Field(default_factory=list, alias="global")
    # Признаки, от которых зависит список оповещения у выбранного правила.
    rule: list[FlagOut] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class PreviewOut(BaseModel):
    """Нижняя полоса служб: кто будет оповещён при текущем заполнении."""

    incident_type: str | None = None
    services: list[NotificationReasonOut] = Field(default_factory=list)


class CallOut(BaseModel):
    """Вызов глазами оператора: он слышит заявителя, но карточки ещё нет."""

    attempt_id: int
    legend: str
    reported_address: str
    caller: str
    # Статус заявителя и номер, определившийся автоматически, оператор видит
    # сразу — как при поступлении вызова в рабочей системе. Остальное
    # он выясняет в разговоре.
    caller_role: str | None
    caller_phone_aon: str | None
    issued_at: str
    deadline_seconds: int
    elapsed_seconds: float
    finished: bool
    chosen_group: str | None
    chosen_path: list[str]
    entered_address: str | None
    entered_description: str | None
    chosen_outcome: str | None
    chosen_referral_target: str | None
    entered_caller_phone: str | None
    entered_address_parts: dict[str, str]
    # Признаки, которые оператор отметил кнопками на карточке.
    chosen_flags: list[str] = Field(default_factory=list)
    # Готовая запись голоса заявителя, если для сценария она озвучена.
    audio_url: str | None
    # Повторная выдача проваленного вызова: тот же заявитель, вторая попытка.
    is_repeat: bool = False
    # Блок «Регистрация и контроль» рабочей карточки: кто и когда
    # зарегистрировал, кто и когда проверил. Ничего нового не хранится —
    # это те же данные попытки и примечание преподавателя, показанные
    # там, где они стоят в настоящей карточке.
    registered_by: str = ""
    registered_at: str | None = None
    control_by: str | None = None
    control_at: str | None = None
    control_note: str | None = None


class ClassifyIn(BaseModel):
    # Что обучающийся решил сделать с обращением. Значение по умолчанию —
    # классификация: так работает подавляющее большинство вызовов, и прежние
    # обращения интерфейса остаются рабочими.
    outcome: CallOutcome = CallOutcome.CLASSIFY
    # Субъект, которому передаётся вызов, — только для передачи
    # по принадлежности.
    referral_target: str = ""
    group: str = ""
    path: list[str] = Field(default_factory=list)
    address: str = ""
    description: str = ""
    caller_phone: str = ""
    # Адрес по частям. Строка `address` остаётся описательной частью:
    # в карточке Системы-112 она есть наравне с формализованным адресом.
    address_parts: dict[str, str] = Field(default_factory=dict)
    # Признаки опросной карты, отмеченные оператором: ключи из `GET /flags`.
    flags: list[str] = Field(default_factory=list)


class ClassificationOut(BaseModel):
    correct: bool
    chosen_incident_type: str | None
    expected_incident_type: str
    matched_depth: int
    expected_depth: int
    # Расхождение по службам: список эталона с признаками вызова против
    # списка по выбору оператора с его признаками. Пропущенный признак
    # проявляется здесь неоповещённой службой.
    missed_services: list[str]
    extra_services: list[str]
    # Признаки: что было в вызове, что отметил оператор и разница.
    expected_flags: list[str] = Field(default_factory=list)
    chosen_flags: list[str] = Field(default_factory=list)
    missed_flags: list[str] = Field(default_factory=list)
    extra_flags: list[str] = Field(default_factory=list)
    # Ложь — у сценария признаки не размечены, и выбор оператора не сверялся:
    # интерфейс не должен рисовать зелёные галочки там, где проверки не было.
    flags_checked: bool = True
    notified_services: dict[str, str]
    # Обоснование по каждой службе: почему она в списке или при каком
    # признаке была бы. Это и есть предмет обучения — список выводится
    # из признаков, а не запоминается.
    notification_reasons: list[NotificationReasonOut] = Field(default_factory=list)


class OperatorEvaluationOut(BaseModel):
    attempt_id: int
    score: float
    # Исход показывается только в разборе, после сдачи карточки: до неё
    # это была бы подсказка, ради которой вызов и придуман.
    expected_outcome: str = str(CallOutcome.CLASSIFY)
    chosen_outcome: str | None = None
    expected_referral_target: str | None = None
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
    forbid_admin_to_student_work(user)
    if attempt.scenario.mode is not TrainingMode.OPERATOR:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Этот сценарий относится к режиму диспетчера ДДС"
        )
    return attempt


# Записи озвучены заранее и разложены по номеру билета и вызова: браузеру
# остаётся проиграть файл. Синтезировать речь на стороне клиента оказалось
# невозможно — в Firefox движок после отмены замолкает до перезагрузки.
TICKET_TITLE = re.compile(r"Билет (\d+), вызов (\d+)")


def _audio_url(scenario: Scenario) -> str | None:
    if scenario.source is not ScenarioSource.TICKET:
        return None
    found = TICKET_TITLE.match(scenario.title)
    return f"/audio/ticket-{found[1]}-{found[2]}.mp3" if found else None


def _call(attempt: Attempt) -> CallOut:
    reference = as_utc(attempt.finished_at) if attempt.finished_at else utcnow()
    evaluation = attempt.evaluation
    controller = evaluation.teacher_feedback_by if evaluation else None
    return CallOut(
        registered_by=attempt.student.full_name,
        registered_at=as_utc(attempt.finished_at).isoformat() if attempt.finished_at else None,
        control_by=controller.full_name if controller else None,
        control_at=(
            as_utc(evaluation.teacher_feedback_at).isoformat()
            if evaluation and evaluation.teacher_feedback_at
            else None
        ),
        control_note=evaluation.teacher_feedback if evaluation else None,
        attempt_id=attempt.id,
        legend=attempt.scenario.description,
        reported_address=attempt.scenario.address,
        caller=attempt.scenario.caller,
        caller_role=str(attempt.scenario.caller_role) if attempt.scenario.caller_role else None,
        caller_phone_aon=attempt.scenario.caller_phone_aon,
        issued_at=as_utc(attempt.issued_at).isoformat(),
        deadline_seconds=attempt.scenario.deadline_seconds or DEFAULT_CALL_DEADLINE_SECONDS,
        elapsed_seconds=(reference - as_utc(attempt.issued_at)).total_seconds(),
        finished=attempt.finished_at is not None,
        chosen_group=attempt.chosen_group,
        chosen_path=list(attempt.chosen_path or []),
        entered_address=attempt.entered_address,
        entered_description=attempt.entered_description,
        chosen_outcome=str(attempt.chosen_outcome) if attempt.chosen_outcome else None,
        chosen_referral_target=attempt.chosen_referral_target,
        entered_caller_phone=attempt.entered_caller_phone,
        entered_address_parts=dict(attempt.entered_address_parts or {}),
        chosen_flags=list(attempt.chosen_flags or []),
        audio_url=_audio_url(attempt.scenario),
        is_repeat=attempt.repeat_of_id is not None,
    )


def _survey_ekp(attempt_id: int | None, db: Session, user: User) -> EKP:
    """Редакция классификатора, по которой строится опросная карта.

    Опросная карта у вызова та же, что и эталон: оператор классифицирует
    по редакции занятия, иначе признаки, которых в его редакции нет,
    засчитывались бы как ошибка. Без вызова — справочный просмотр
    по действующей редакции.
    """
    if attempt_id is None:
        return current_ekp(db)
    return ekp_for_session(_load(attempt_id, db, user).session)


def _split_path(path: str) -> list[str]:
    """Путь признаков из строки запроса: через «|», пустые звенья отбрасываются."""
    return [p for p in path.split("|") if p]


@router.get("/groups", response_model=list[str])
def groups(
    attempt_id: int | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[str]:
    """Категории происшествий верхнего уровня опросной карты."""
    return sorted(survey_tree(_survey_ekp(attempt_id, db, user)))


@router.get("/options", response_model=list[OptionOut])
def options(
    group: str,
    path: str = "",
    attempt_id: int | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[OptionOut]:
    """Признаки, доступные на текущем шаге. Путь передаётся через «|»."""
    selected = _split_path(path)
    ekp = _survey_ekp(attempt_id, db, user)
    return [OptionOut(**o) for o in options_at(group, selected, ekp)]


@router.get("/flags", response_model=FlagsOut, response_model_by_alias=True)
def flags(
    group: str = "",
    path: str = "",
    attempt_id: int | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FlagsOut:
    """Какие кнопки признаков показывать на карточке.

    Три глобальные — всегда, как в АРМ-112. Остальные зависят от правила,
    к которому привёл путь: пока путь не доведён, показывать нечего —
    неизвестно ещё, чей список оповещения эти признаки меняют.
    """
    ekp = _survey_ekp(attempt_id, db, user)
    rule = resolve(group, _split_path(path), ekp) if group else None
    return FlagsOut(
        global_=[FlagOut(**vars(f)) for f in flag_titles.global_flags()],
        rule=[FlagOut(**vars(f)) for f in flag_titles.flags_for_rule(rule)] if rule else [],
    )


@router.get("/preview", response_model=PreviewOut)
def preview(
    group: str = "",
    path: str = "",
    flags: str = "",
    attempt_id: int | None = None,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PreviewOut:
    """Список оповещения по текущему заполнению карточки.

    Это то, что настоящий АРМ-112 показывает в полосе служб по мере
    заполнения: считается по правилу и признакам, которые выбрал оператор,
    а не по эталону, — подсказкой быть не должно. Неоповещённые службы
    не возвращаются: в рабочей полосе их нет, а объяснение «кого не хватило»
    остаётся разбору после сдачи.
    """
    ekp = _survey_ekp(attempt_id, db, user)
    rule = resolve(group, _split_path(path), ekp) if group else None
    if rule is None:
        return PreviewOut()
    chosen = frozenset(_split_path(flags))
    return PreviewOut(
        incident_type=rule.incident_type,
        services=[
            NotificationReasonOut.from_reason(r) for r in rule.explain(chosen) if r.notified
        ],
    )


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
    # Правило классификатора нужно только там, где вызов положено
    # классифицировать. У происшествия в другом субъекте правильного правила
    # в московском классификаторе нет и быть не может.
    if (
        scenario.expected_outcome is CallOutcome.CLASSIFY
        and scenario.ekp_rule_number is None
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Сценарий не привязан к классификатору"
        )

    # Оценка идёт по редакции занятия. Сценарий мог быть составлен по другой
    # редакции, где правило с этим номером было, а в редакции занятия его
    # нет, — тогда эталона нет и оценивать не по чему.
    ekp = ekp_for_session(attempt.session)
    if scenario.expected_outcome is CallOutcome.CLASSIFY:
        try:
            ekp.rule(scenario.ekp_rule_number)
        except KeyError:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Правила № {scenario.ekp_rule_number} нет в редакции "
                "классификатора, по которой идёт занятие",
            ) from None

    # Ключи признаков — только те, что есть в редакции занятия: чужой ключ
    # список оповещения не изменит, и оператор решил бы, что нажал кнопку,
    # которой не было.
    chosen_flags = list(dict.fromkeys(payload.flags))
    allowed = flag_titles.known_keys(ekp)
    unknown = sorted(set(chosen_flags) - allowed)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Неизвестные признаки: "
            + ", ".join(unknown)
            + ". Допустимые: "
            + ", ".join(sorted(allowed)),
        )

    now = utcnow()
    attempt.chosen_group = payload.group or None
    attempt.chosen_path = list(payload.path)
    attempt.chosen_flags = chosen_flags
    attempt.entered_address = payload.address.strip() or None
    attempt.entered_description = payload.description.strip() or None
    attempt.entered_caller_phone = payload.caller_phone.strip() or None
    attempt.entered_address_parts = {
        k: v.strip() for k, v in payload.address_parts.items() if v and v.strip()
    }
    attempt.chosen_outcome = payload.outcome
    attempt.chosen_referral_target = payload.referral_target.strip() or None
    attempt.finished_at = now

    deadline = scenario.deadline_seconds or DEFAULT_CALL_DEADLINE_SECONDS
    assessment = evaluate_card(
        FilledCard(
            group=payload.group or None,
            path=tuple(payload.path),
            address=payload.address,
            description=payload.description,
            elapsed_seconds=(now - as_utc(attempt.issued_at)).total_seconds(),
            outcome=payload.outcome,
            referral_target=payload.referral_target,
            caller_phone=payload.caller_phone,
            address_parts=attempt.entered_address_parts,
            flags=frozenset(chosen_flags),
        ),
        Expected(
            outcome=scenario.expected_outcome,
            rule_number=scenario.ekp_rule_number,
            referral_target=scenario.referral_target,
            contact_phone=scenario.contact_phone,
            address_parts=dict(scenario.address_parts or {}),
            flags=frozenset(scenario.flags or []),
        ),
        deadline,
        ekp,
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
    complete_attempt(db, attempt, evaluation, background)

    return _out(attempt, evaluation, assessment)


def _out(attempt: Attempt, evaluation: Evaluation, assessment) -> OperatorEvaluationOut:
    classification = None
    if assessment.classification is not None:
        result = assessment.classification
        chosen = result.chosen_rule
        # Признаки вызова — из сценария: список оповещения и его обоснование
        # обязаны совпадать с тем, что видит диспетчер на карточке.
        flags = frozenset(attempt.scenario.flags or [])
        chosen_flags = frozenset(attempt.chosen_flags or [])
        classification = ClassificationOut(
            correct=result.correct,
            chosen_incident_type=chosen.incident_type if chosen else None,
            expected_incident_type=result.expected_rule.incident_type,
            matched_depth=result.matched_depth,
            expected_depth=result.expected_depth,
            missed_services=list(result.missed_services),
            extra_services=list(result.extra_services),
            expected_flags=sorted(flags),
            chosen_flags=list(attempt.chosen_flags or []),
            # Без размеченных признаков сверки не было — пропущенных и лишних
            # нет по определению, а не потому, что оператор всё угадал.
            missed_flags=sorted(flags - chosen_flags) if flags else [],
            extra_flags=sorted(chosen_flags - flags) if flags else [],
            flags_checked=bool(flags),
            # Эталонное правило уже взято из редакции занятия — список
            # оповещения берётся из него же, а не ищется заново.
            notified_services=result.expected_rule.resolve(flags),
            notification_reasons=[
                NotificationReasonOut.from_reason(r) for r in result.expected_rule.explain(flags)
            ],
        )
    return OperatorEvaluationOut(
        attempt_id=attempt.id,
        score=evaluation.score,
        expected_outcome=str(attempt.scenario.expected_outcome),
        chosen_outcome=str(attempt.chosen_outcome) if attempt.chosen_outcome else None,
        expected_referral_target=attempt.scenario.referral_target,
        violations=list(evaluation.violations),
        classification=classification,
        llm_pending=evaluation.llm_pending,
        llm_available=evaluation.llm_available,
        llm_summary=evaluation.llm_summary,
        grammar_issues=list(evaluation.grammar_issues or []),
    )
