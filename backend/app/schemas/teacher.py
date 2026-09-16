from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class CatalogOut(BaseModel):
    """Справочники для настройки занятия."""

    groups: list[str]
    services: list[ServiceOut]
    difficulties: dict[int, str]


class GenerateIn(BaseModel):
    group: str
    count: int = Field(default=5, ge=1, le=20)
    difficulty: int = Field(default=2, ge=1, le=3)
    service_id: int


class ScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    incident_type: str
    group: str | None = None
    address: str
    description: str
    caller: str
    difficulty: int
    source: str
    expected_primary_status: str
    is_profile: bool
    required_comment_points: list[str]
    service_name: str
    # Список оповещения по ЕКП — показывает, на чём основан эталон.
    notified_services: dict[str, str] = Field(default_factory=dict)
    approved: bool
    approved_at: datetime | None = None
    teacher_note: str | None = None


class GenerateOut(BaseModel):
    requested: int
    created: int
    scenarios: list[ScenarioOut]
    # Заполняется, если модель сформировала меньше, чем просили.
    warning: str | None = None


class CorrectIn(BaseModel):
    """Замечание преподавателя, по которому сценарий формируется заново."""

    note: str = Field(min_length=3, max_length=1000)


class ScenarioEditIn(BaseModel):
    description: str | None = None
    address: str | None = None
    expected_primary_status: str | None = None
    required_comment_points: list[str] | None = None
    difficulty: int | None = Field(default=None, ge=1, le=3)


class StudentResultOut(BaseModel):
    student_id: int
    student_name: str
    attempts: int
    finished: int
    average_score: float
    overdue: int
    violations: dict[str, int]


class ReportOut(BaseModel):
    """Отчёт о практическом занятии — требование технического задания."""

    session_id: int
    title: str
    state: str
    deadline_seconds: int
    started_at: datetime | None
    finished_at: datetime | None
    students: list[StudentResultOut]
    total_attempts: int
    finished_attempts: int
    average_score: float
    average_response_seconds: float | None
    overdue_share: float
    violations: dict[str, int]
    grammar_issues: int
    # Инсайты по типичным ошибкам группы — тоже требование ТЗ.
    insights: list[str]
