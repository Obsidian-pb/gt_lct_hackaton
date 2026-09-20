from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    full_name: str
    role: str
    service_name: str | None = None
    # Имя службы в классификаторе — по нему интерфейс подсвечивает свой блок.
    service_ekp_name: str | None = None


class CardOut(BaseModel):
    """Карточка происшествия глазами диспетчера ДДС."""

    attempt_id: int
    incident_type: str
    address: str
    description: str
    caller: str
    # Службы, оповещённые по этому происшествию согласно ЕКП.
    notified_services: dict[str, str] = Field(default_factory=dict)
    issued_at: datetime
    opened_at: datetime | None
    pickup_deadline_seconds: int
    handling_deadline_seconds: int
    elapsed_seconds: float
    # Фактические значения: сколько ушло на взятие в работу и на обработку.
    pickup_seconds: float | None = None
    handling_seconds: float | None = None
    current_status: str | None
    available_statuses: list[str]
    comment_required_for: list[str]
    card_status: str
    finished: bool


class StatusIn(BaseModel):
    status: str
    comment: str | None = None


class ViolationOut(BaseModel):
    code: str
    title: str
    criterion: str
    severity: str
    detail: str
    evidence: str | None = None
    example: str | None = None


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt_id: int
    score: float
    criteria: dict[str, bool]
    violations: list[ViolationOut]
    llm_pending: bool
    llm_available: bool
    llm_summary: str | None = None
    grammar_issues: list[str] = Field(default_factory=list)
    # Примечание преподавателя к этой работе. Показывается вместе с автором
    # и временем: обучающийся должен видеть, кто и когда его оставил.
    teacher_feedback: str | None = None
    teacher_feedback_at: datetime | None = None
    teacher_feedback_by: str | None = None
