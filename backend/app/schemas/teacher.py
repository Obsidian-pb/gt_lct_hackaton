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
    mode: str = "dispatcher"
    group: str | None = None
    address: str
    description: str
    caller: str
    difficulty: int
    source: str
    expected_primary_status: str
    # Эталонный исход обращения. Преподаватель обязан видеть, что вызов —
    # ловушка: иначе он не сможет проверить эталон, а утверждает сценарий он.
    expected_outcome: str = "classify"
    referral_target: str | None = None
    is_profile: bool
    required_comment_points: list[str]
    service_name: str
    # Список оповещения по ЕКП — показывает, на чём основан эталон.
    notified_services: dict[str, str] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    approved: bool
    approved_at: datetime | None = None
    teacher_note: str | None = None


class GenerationJobOut(BaseModel):
    """Ход формирования карточек: страница опрашивает его, пока не done."""

    id: int
    state: str
    group: str
    service_name: str
    requested: int
    finished: int
    created: int
    scenario_ids: list[int]
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    # Заполняется по завершении, если модель сформировала меньше, чем просили.
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
    # Признаки опросной карты вызова: то, что заявитель назвал и что оператор
    # обязан отметить. Правятся руками, когда автоматический разбор речи
    # промолчал или ошибся.
    flags: list[str] | None = None


class GrammarCheckOut(BaseModel):
    """Замечания к тексту сценария после ручной правки преподавателем."""

    scenario_id: int
    issues: list[str]
    # Что именно проверялось: преподаватель должен понимать, к какому тексту
    # относятся замечания, — часть полей сценария в проверку не идёт.
    checked_fields: list[str]


class FeedbackIn(BaseModel):
    """Примечание преподавателя к конкретной работе обучающегося."""

    text: str = Field(min_length=3, max_length=2000)


class WorkOut(BaseModel):
    """Работа обучающегося глазами преподавателя — строка для обратной связи."""

    attempt_id: int
    student_id: int
    student_name: str
    scenario_title: str
    finished_at: datetime | None
    score: float | None
    violations: int
    critical: int
    teacher_feedback: str | None = None
    teacher_feedback_at: datetime | None = None
    # ФИО автора примечания: результаты обучения нельзя менять без следа.
    teacher_feedback_by: str | None = None
    # Заполнено у повторной выдачи: номер проваленной попытки.
    repeat_of_id: int | None = None


class RepeatResultOut(BaseModel):
    """Итог повторной выдачи проваленной карточки."""

    attempt_id: int
    repeat_attempt_id: int
    scenario_title: str
    first_score: float | None
    repeat_score: float | None
    # None — повтор ещё не завершён.
    fixed: bool | None


class StudentResultOut(BaseModel):
    student_id: int
    student_name: str
    attempts: int
    finished: int
    average_score: float
    overdue: int
    violations: dict[str, int]
    critical: int = 0
    # None — завершённых работ нет, судить о зачёте не по чему.
    passed: bool | None = None
    # Повторные выдачи — отдельно: в средний балл и зачёт они не входят.
    repeats: list[RepeatResultOut] = Field(default_factory=list)


class ReportOut(BaseModel):
    """Отчёт о практическом занятии — требование технического задания."""

    session_id: int
    title: str
    state: str
    pickup_deadline_seconds: int
    handling_deadline_seconds: int
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
    # Критерии успешности занятия и итог по ним.
    pass_score: float
    max_critical_violations: int
    passed_students: int
    failed_students: int
    # Повторные выдачи проваленных карточек: выдано, завершено, исправились.
    repeats_issued: int = 0
    repeats_finished: int = 0
    repeats_fixed: int = 0


class SessionIn(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    mode: str = "dispatcher"
    pickup_deadline_seconds: int = Field(default=30, ge=5, le=300)
    handling_deadline_seconds: int = Field(default=180, ge=30, le=1800)
    # Интервал между вызовами — регулятор нагрузки: чем меньше, тем больше
    # карточек висит на обучающемся одновременно.
    call_interval_seconds: int = Field(default=20, ge=0, le=600)
    # Критерии успешности: порог среднего балла и допустимое число критических
    # нарушений. Умолчания повторяют значения колонок — занятие, созданное
    # без явных критериев, оценивается так же, как и прежде.
    pass_score: float = Field(default=0.7, ge=0, le=1)
    max_critical_violations: int = Field(default=0, ge=0, le=100)
    # Возвращать ли проваленную карточку обучающемуся в том же занятии.
    repeat_failed: bool = False


class SessionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=255)
    pickup_deadline_seconds: int | None = Field(default=None, ge=5, le=300)
    handling_deadline_seconds: int | None = Field(default=None, ge=30, le=1800)
    call_interval_seconds: int | None = Field(default=None, ge=0, le=600)
    pass_score: float | None = Field(default=None, ge=0, le=1)
    max_critical_violations: int | None = Field(default=None, ge=0, le=100)
    repeat_failed: bool | None = None
    student_ids: list[int] | None = None
    # Состав можно задать группой: её участники копируются в занятие.
    # Именно копируются, а не связываются ссылкой — иначе правка группы
    # задним числом переписала бы состав уже проведённого занятия.
    group_id: int | None = None
    scenario_ids: list[int] | None = None


class GroupIn(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    note: str | None = Field(default=None, max_length=500)
    student_ids: list[int] = Field(default_factory=list)


class GroupPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=255)
    note: str | None = Field(default=None, max_length=500)
    student_ids: list[int] | None = None


class GroupOut(BaseModel):
    id: int
    title: str
    note: str | None
    teacher_name: str
    students: list[dict]


class SessionOut(BaseModel):
    id: int
    title: str
    mode: str
    state: str
    pickup_deadline_seconds: int
    handling_deadline_seconds: int
    call_interval_seconds: int
    pass_score: float
    max_critical_violations: int
    repeat_failed: bool = False
    started_at: datetime | None
    finished_at: datetime | None
    students: list[dict]
    scenarios: list[dict]
    # Сколько карточек получит каждый обучающийся при запуске.
    approved_scenarios: int
    # Обозначение редакции классификатора, по которой идёт занятие.
    # None — встроенная редакция из файла поставки.
    classifier_version_label: str | None = None


class ProgressOut(BaseModel):
    student_id: int
    student_name: str
    issued: int
    opened: int
    finished: int
    overdue_pickup: int
    in_work: int
    # Сколько из поступивших карточек — повторные выдачи.
    repeats: int = 0


class MonitorOut(BaseModel):
    """Ход занятия в реальном времени — требование ТЗ о контроле во время."""

    session_id: int
    state: str
    started_at: datetime | None
    call_interval_seconds: int
    pickup_deadline_seconds: int
    total_planned: int
    issued: int
    finished: int
    students: list[ProgressOut]
