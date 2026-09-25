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


class NotificationReasonOut(BaseModel):
    """Служба из списка оповещения и почему она там — или почему нет."""

    service: str
    incident_type: str
    notified: bool
    reason: str

    @classmethod
    def from_reason(cls, reason) -> "NotificationReasonOut":
        return cls(
            service=reason.service,
            incident_type=reason.incident_type_in_service,
            notified=reason.notified,
            reason=reason.text,
        )


class CardOut(BaseModel):
    """Карточка происшествия глазами диспетчера ДДС."""

    attempt_id: int
    incident_type: str
    address: str
    description: str
    caller: str
    # Службы, оповещённые по этому происшествию согласно ЕКП.
    notified_services: dict[str, str] = Field(default_factory=dict)
    # Обоснование списка: по какому признаку каждая служба в нём оказалась.
    notification_reasons: list[NotificationReasonOut] = Field(default_factory=list)
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
    # Повторная выдача проваленной карточки: тот же вызов, вторая попытка.
    # Эталон при этом не раскрывается — обучающийся видит только пометку.
    is_repeat: bool = False


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
    # Итоговый балл преподавателя; пусто — итог равен машинному score.
    final_score: float | None = None
    teacher_feedback_by: str | None = None
