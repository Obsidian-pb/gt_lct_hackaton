from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Integer, LargeBinary, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.user import DispatchService, User


class TrainingMode(StrEnum):
    """Кого обучаем.

    DISPATCHER — диспетчер ДДС: получает готовую карточку и проставляет
    статус реагирования. OPERATOR — оператор Службы 112: принимает вызов
    и сам классифицирует происшествие по опросной карте.
    """

    DISPATCHER = "dispatcher"
    OPERATOR = "operator"


class CallOutcome(StrEnum):
    """Что оператор Службы 112 обязан сделать с обращением.

    Классификация — не единственный правильный исход, и экзаменационные
    билеты это проверяют. Происшествие в другом субъекте Москва
    не обслуживает: его передают по принадлежности, а не заводят карточку.
    Обращение, которое происшествием не является, не регистрируют вовсе.
    """

    CLASSIFY = "classify"
    REFER = "refer"
    REJECT = "reject"


class CallerRole(StrEnum):
    """Кем заявитель приходится происшествию.

    Участник, очевидец и родственник знают о происшествии разное: участник
    сообщает о себе, очевидец видит со стороны и может ошибаться в деталях,
    родственник передаёт с чужих слов и часто не на месте. Оператор обязан
    это учитывать — от статуса зависит, каким сведениям верить и какой
    телефон записывать для связи.
    """

    PARTICIPANT = "participant"
    WITNESS = "witness"
    RELATIVE = "relative"


class ScenarioSource(StrEnum):
    MANUAL = "manual"
    GENERATED = "generated"
    TICKET = "ticket"


class SessionState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    FINISHED = "finished"


class CardStatus(StrEnum):
    """Статусы карточки происшествия из памятки ГБУ «Система 112»."""

    REGISTERED = "Зарегистрирована"
    NOT_NOTIFIED = "Не оповещено"
    REFUSED = "Отказ"
    UNFINISHED = "Не завершено"
    COMPLETED = "Завершена"


# Состав занятия: кого учим и на каких сценариях. Отдельные таблицы, а не
# списки в JSON, чтобы по ним можно было делать выборки и считать отчёт.
session_student = Table(
    "session_student",
    Base.metadata,
    Column("session_id", ForeignKey("training_session.id"), primary_key=True),
    Column("student_id", ForeignKey("app_user.id"), primary_key=True),
)

# Состав учебной группы. Группа — это именованный список обучающихся,
# который преподаватель собирает один раз и потом переиспользует: набор
# курса, смена, поток. В занятие состав попадает копированием, а не ссылкой,
# поэтому изменение группы задним числом не переписывает уже проведённое
# занятие.
study_group_student = Table(
    "study_group_student",
    Base.metadata,
    Column("group_id", ForeignKey("study_group.id"), primary_key=True),
    Column("student_id", ForeignKey("app_user.id"), primary_key=True),
)

session_scenario = Table(
    "session_scenario",
    Base.metadata,
    Column("session_id", ForeignKey("training_session.id"), primary_key=True),
    Column("scenario_id", ForeignKey("scenario.id"), primary_key=True),
)


class StudyGroup(Base, TimestampMixin):
    """Учебная группа — постоянный список обучающихся.

    Техническое задание требует от преподавателя назначать учащимся «конкретные
    задания и группы». Задания назначаются составом занятия, а группа избавляет
    от того, чтобы собирать одних и тех же людей заново к каждому занятию.
    """

    __tablename__ = "study_group"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), unique=True)
    note: Mapped[str | None] = mapped_column(String(500))

    teacher_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    teacher: Mapped[User] = relationship()
    students: Mapped[list[User]] = relationship(secondary=study_group_student)


class Scenario(Base, TimestampMixin):
    """Учебный сценарий: карточка происшествия вместе с эталоном действий.

    Сценарий обязан быть утверждён преподавателем перед выдачей обучающимся —
    сгенерированные нейросетью карточки без подтверждения в занятие не идут.
    """

    __tablename__ = "scenario"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    mode: Mapped[TrainingMode] = mapped_column(
        SAEnum(TrainingMode, native_enum=False, length=32), default=TrainingMode.DISPATCHER
    )
    source: Mapped[ScenarioSource] = mapped_column(
        SAEnum(ScenarioSource, native_enum=False, length=32), default=ScenarioSource.MANUAL
    )
    difficulty: Mapped[int] = mapped_column(Integer, default=1)

    # Привязка к ЕКП: по номеру правила восстанавливаются итоговый тип
    # происшествия и список оповещения.
    ekp_rule_number: Mapped[int | None] = mapped_column(Integer, index=True)
    incident_type: Mapped[str] = mapped_column(String(255))
    # Флаги опросной карты, влияющие на список оповещения.
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)

    address: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    caller: Mapped[str] = mapped_column(String(255), default="")
    # Кем заявитель приходится происшествию. Пусто у сценариев, заведённых
    # до появления поля: выдумывать статус задним числом нельзя.
    caller_role: Mapped[CallerRole | None] = mapped_column(
        SAEnum(CallerRole, native_enum=False, length=32)
    )
    # Три телефона — так устроена настоящая карточка Системы-112.
    # АОН определяется автоматически при поступлении вызова и оператору
    # виден сразу. Номер со слов заявителя может от него отличаться:
    # человек звонит с чужого телефона и просит перезвонить на свой.
    # Телефон на месте нужен, когда заявитель сам не на месте происшествия.
    caller_phone_aon: Mapped[str | None] = mapped_column(String(32))
    caller_phone_stated: Mapped[str | None] = mapped_column(String(32))
    caller_phone_onsite: Mapped[str | None] = mapped_column(String(32))

    # Адрес по частям: субъект, населённый пункт, улица, дом, корпус,
    # строение, квартира, подъезд, этаж, код домофона. Хранится словарём,
    # а не десятком столбцов: состав частей задан предметной областью
    # и меняется вместе с ней, а каждая правка столбцами — это миграция.
    # Строка `address` остаётся описательной частью, как в рабочей карточке.
    address_parts: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")

    @property
    def contact_phone(self) -> str | None:
        """Номер, по которому связываться: со слов заявителя, иначе АОН.

        Порядок именно такой: если заявитель назвал другой номер, значит
        на АОН его не застать — он звонит с чужого телефона.
        """
        return self.caller_phone_stated or self.caller_phone_aon

    target_service_id: Mapped[int] = mapped_column(ForeignKey("dispatch_service.id"))
    target_service: Mapped[DispatchService] = relationship()

    # --- Эталон -------------------------------------------------------------
    expected_primary_status: Mapped[str] = mapped_column(String(64))
    is_profile: Mapped[bool] = mapped_column(Boolean, default=True)
    expects_progress_statuses: Mapped[bool] = mapped_column(Boolean, default=False)
    required_comment_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    deadline_seconds: Mapped[int] = mapped_column(Integer, default=30)

    author_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    author: Mapped[User] = relationship(foreign_keys=[author_id])
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id])
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Замечание преподавателя, по которому система переформирует сценарий.
    teacher_note: Mapped[str | None] = mapped_column(Text)

    # Ожидаемый исход обращения. По умолчанию — классификация: так устроено
    # подавляющее большинство сценариев, и прежние записи остаются верными.
    expected_outcome: Mapped[CallOutcome] = mapped_column(
        SAEnum(CallOutcome, native_enum=False, length=32),
        default=CallOutcome.CLASSIFY,
        # В столбце хранится имя элемента, а не значение: так устроены
        # остальные перечисления схемы (OPERATOR, TICKET), и значение
        # по умолчанию должно быть записано так же.
        server_default=CallOutcome.CLASSIFY.name,
    )
    # Куда передавать при исходе «передача по принадлежности»: субъект
    # Российской Федерации, чья система-112 обслуживает этот адрес.
    referral_target: Mapped[str | None] = mapped_column(String(255))

    @property
    def is_approved(self) -> bool:
        return self.approved_at is not None


class ClassifierVersion(Base, TimestampMixin):
    """Редакция Единого классификатора происшествий, загруженная в комплекс.

    Классификатор правится не реже раза в год, и техническое задание требует
    механизма импорта обновлений учебных материалов. Хранится сам разобранный
    файл, а не ссылка на него: занятие, проведённое по прежней редакции,
    должно и через год оцениваться по ней же — иначе отчёт разойдётся
    с тем, что обучающийся видел на экране.

    Пустая ссылка у занятия означает встроенную редакцию из файла поставки.
    """

    __tablename__ = "classifier_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(64), unique=True)
    source_name: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64))
    rule_count: Mapped[int] = mapped_column(Integer)
    # Разобранный классификатор в том же виде, что и файл поставки
    # `data/ekp.json`: так одна и та же загрузка обслуживает обе редакции.
    # Столбец отложенный: это мегабайты, а список редакций и привязка
    # занятия к редакции обходятся обозначением и контрольной суммой.
    # На схему это не влияет — только на то, когда столбец читается.
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    note: Mapped[str | None] = mapped_column(String(500))

    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    uploaded_by: Mapped[User] = relationship()


class TrainingSession(Base, TimestampMixin):
    """Практическое занятие, которым управляет преподаватель."""

    __tablename__ = "training_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    mode: Mapped[TrainingMode] = mapped_column(
        SAEnum(TrainingMode, native_enum=False, length=32), default=TrainingMode.DISPATCHER
    )
    state: Mapped[SessionState] = mapped_column(
        SAEnum(SessionState, native_enum=False, length=32), default=SessionState.DRAFT
    )
    # Два норматива, заданных организаторами, измеряют разное.
    # Взятие в работу — дисциплина реакции: от поступления вызова до открытия
    # карточки. Обработка — качество работы по существу: от взятия в работу
    # до завершения.
    pickup_deadline_seconds: Mapped[int] = mapped_column(Integer, default=30)
    handling_deadline_seconds: Mapped[int] = mapped_column(Integer, default=180)
    # Интервал между поступлением вызовов — основной регулятор сложности.
    # Чем он меньше, тем больше карточек висит одновременно и тем жёстче
    # проверяется умение расставлять приоритеты.
    call_interval_seconds: Mapped[int] = mapped_column(Integer, default=20)
    # Критерии успешности занятия. Балл ниже порога или больше допустимого
    # числа критических нарушений — работа не зачтена. Значения по умолчанию
    # соответствуют прежнему поведению отчёта, где порога не было вовсе.
    pass_score: Mapped[float] = mapped_column(
        Float, default=0.7, server_default="0.7"
    )
    max_critical_violations: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    # Возвращать ли проваленную карточку обучающемуся в том же занятии.
    # Повтор идёт тем же сценарием после остальных карточек: ошибка
    # разбирается по горячим следам, а не на следующей неделе.
    repeat_failed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Редакция классификатора, по которой проводится занятие. Пусто —
    # встроенная редакция из файла поставки; так устроены все занятия,
    # проведённые до появления загрузки редакций.
    classifier_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("classifier_version.id", name="fk_training_session_classifier_version")
    )
    classifier_version: Mapped[ClassifierVersion | None] = relationship()

    teacher_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    teacher: Mapped[User] = relationship()

    students: Mapped[list[User]] = relationship(secondary=session_student)
    scenarios: Mapped[list["Scenario"]] = relationship(secondary=session_scenario)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    attempts: Mapped[list["Attempt"]] = relationship(back_populates="session")


class TrainingMaterial(Base, TimestampMixin):
    """Методический материал справочной базы.

    Техническое задание требует двух вещей сразу: обучающийся должен
    просматривать инструкции и методические материалы, преподаватель —
    создавать их и загружать дополнительные ресурсы. Поэтому материал
    может быть как написанным текстом, так и приложенным файлом,
    и одно другого не исключает.

    Файл хранится в базе, а не в томе на диске: учебный комплекс работает
    в изолированном контуре, материалы невелики, а резервная копия базы
    тогда содержит и их — иначе восстановление вернуло бы ссылки на файлы,
    которых уже нет.
    """

    __tablename__ = "training_material"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)

    file_name: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str | None] = mapped_column(String(128))
    content: Mapped[bytes | None] = mapped_column(LargeBinary)
    size_bytes: Mapped[int | None] = mapped_column(Integer)

    # Черновик виден только автору: незаконченная методичка не должна
    # попадать к обучающимся, как и неутверждённый сценарий.
    published: Mapped[bool] = mapped_column(Boolean, default=False)

    author_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    author: Mapped[User] = relationship()


class Attempt(Base, TimestampMixin):
    """Работа одного обучающегося с одной карточкой."""

    __tablename__ = "attempt"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("training_session.id"))
    session: Mapped[TrainingSession] = relationship(back_populates="attempts")
    student_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    student: Mapped[User] = relationship()
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenario.id"))
    scenario: Mapped[Scenario] = relationship()

    # Если карточка выдана повторно после провала — ссылка на проваленную
    # попытку. По ней в отчёте видно, исправился ли обучающийся, а сама
    # повторная попытка не участвует в подсчёте среднего балла первого
    # прохода. Повтор повтора не выдаётся.
    repeat_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("attempt.id", name="fk_attempt_repeat_of")
    )
    repeat_of: Mapped["Attempt | None"] = relationship(remote_side="Attempt.id")

    # Точка отсчёта норматива: момент направления карточки в службу.
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Момент открытия карточки — статус «Получена службой».
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    card_status: Mapped[CardStatus] = mapped_column(
        SAEnum(CardStatus, native_enum=False, length=32), default=CardStatus.REGISTERED
    )

    # --- Режим оператора 112 -------------------------------------------------
    # Что обучающийся выбрал в опросной карте и ввёл в карточку вручную.
    chosen_group: Mapped[str | None] = mapped_column(String(255))
    chosen_path: Mapped[list[str]] = mapped_column(JSON, default=list)
    entered_address: Mapped[str | None] = mapped_column(String(500))
    entered_description: Mapped[str | None] = mapped_column(Text)
    # Телефон для связи, записанный обучающимся со слов заявителя.
    entered_caller_phone: Mapped[str | None] = mapped_column(String(32))
    # Адрес, записанный обучающимся по частям.
    entered_address_parts: Mapped[dict] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    # Какой исход выбрал обучающийся: классифицировать, передать
    # по принадлежности или отказать в регистрации.
    chosen_outcome: Mapped[CallOutcome | None] = mapped_column(
        SAEnum(CallOutcome, native_enum=False, length=32)
    )
    chosen_referral_target: Mapped[str | None] = mapped_column(String(255))
    # Признаки опросной карты, которые оператор отметил сам: пострадавшие,
    # нет доступа, угроза людям. В настоящем АРМ-112 это кнопки на карточке,
    # и от них зависит список оповещения — значит, услышать признак в вызове
    # и отметить его входит в то, чему учим. Эталон — `Scenario.flags`.
    chosen_flags: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")

    events: Mapped[list["StatusEvent"]] = relationship(
        back_populates="attempt",
        order_by="StatusEvent.elapsed_seconds",
        cascade="all, delete-orphan",
    )
    evaluation: Mapped["Evaluation | None"] = relationship(
        back_populates="attempt", uselist=False, cascade="all, delete-orphan"
    )


class StatusEvent(Base, TimestampMixin):
    """Проставленный обучающимся статус реагирования с комментарием."""

    __tablename__ = "status_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempt.id"))
    attempt: Mapped[Attempt] = relationship(back_populates="events")

    status: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(Text)
    # Секунды от момента направления карточки — по ним считается норматив.
    elapsed_seconds: Mapped[float] = mapped_column(Float)


class Evaluation(Base, TimestampMixin):
    """Результат оценки попытки.

    Детерминированная часть заполняется сразу, поля LLM дозаполняются фоновой
    задачей — поэтому llm_pending остаётся истинным до её завершения.
    """

    __tablename__ = "evaluation"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempt.id"), unique=True)
    attempt: Mapped[Attempt] = relationship(back_populates="evaluation")

    score: Mapped[float] = mapped_column(Float)
    criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    violations: Mapped[list[dict]] = mapped_column(JSON, default=list)

    llm_pending: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_available: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_summary: Mapped[str | None] = mapped_column(Text)
    grammar_issues: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Обратная связь преподавателя по этой работе — то, чего не даёт
    # автоматический разбор: что именно сказать обучающемуся. Хранится
    # вместе с автором и временем, потому что оценка, изменённая без следа
    # в журнале, техническим заданием запрещена.
    teacher_feedback: Mapped[str | None] = mapped_column(Text)
    teacher_feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    teacher_feedback_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    teacher_feedback_by: Mapped[User | None] = relationship()


class GenerationState(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class GenerationJob(Base, TimestampMixin):
    """Задание на формирование карточек языковой моделью.

    Модель на процессоре пишет карточку около минуты, а преподаватель просит
    пять или десять. Держать запрос открытым всё это время нельзя: кнопка
    «думает» шесть минут, а любой обрыв связи теряет уже готовое. Поэтому
    формирование идёт в фоне, по одной карточке, и каждая готовая сразу
    сохраняется черновиком. Задание хранится в базе, а не в памяти процесса:
    после перезапуска сервера преподаватель должен увидеть, на чём всё
    остановилось, а не пустой экран.
    """

    __tablename__ = "generation_job"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    teacher: Mapped[User] = relationship()
    group: Mapped[str] = mapped_column(String(255))
    difficulty: Mapped[int] = mapped_column(Integer, default=2)
    service_id: Mapped[int] = mapped_column(ForeignKey("dispatch_service.id"))
    service: Mapped[DispatchService] = relationship()

    requested: Mapped[int] = mapped_column(Integer)
    # Сколько запросов к модели уже завершилось (удачно или нет) и сколько
    # карточек из них получилось. Разница — отказы модели.
    finished: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    state: Mapped[GenerationState] = mapped_column(
        SAEnum(GenerationState, native_enum=False, length=16),
        default=GenerationState.RUNNING,
        server_default=GenerationState.RUNNING.name,
    )
    # Номера созданных сценариев — чтобы страница подсветила новые карточки.
    scenario_ids: Mapped[list[int]] = mapped_column(JSON, default=list, server_default="[]")
    error: Mapped[str | None] = mapped_column(String(500))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def done(self) -> bool:
        return self.state is not GenerationState.RUNNING
