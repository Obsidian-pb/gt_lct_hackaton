"""Кабинет администратора: учётные записи, журнал аудита, состояние системы.

Ограничение из технического задания соблюдено намеренно: администратор
не имеет доступа к результатам обучения и оценкам. Он управляет доступом
и техническим состоянием, а персональные данные об успеваемости видит
только преподаватель — это принцип минимальных привилегий.

Второе ограничение того же раздела ТЗ — невмешательство в учебный процесс
во время активного занятия — проверяется при правке учётной записи, см.
`_running_session_of`. Необратимого удаления данных в кабинете нет вовсе:
учётные записи блокируются, а не стираются, и записи журнала аудита не
удаляются ничем — поэтому требование «не удалять без резервного
копирования» здесь просто нечему нарушить.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import get_settings
from app.core.db import get_session
from app.core.security import hash_password
from app.models.audit import AuditAction, AuditEvent
from app.models.training import Attempt, Scenario, SessionState, TrainingSession
from app.models.user import DispatchService, Role, User
from app.services import audit
from app.services.ekp import get_ekp

router = APIRouter(prefix="/api/admin", tags=["Кабинет администратора"])


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    full_name: str
    role: str
    is_active: bool
    service_id: int | None = None
    service_name: str | None = None
    created_at: datetime


class UserIn(BaseModel):
    login: str = Field(min_length=3, max_length=150)
    full_name: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=200)
    role: Role
    service_id: int | None = None


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=3, max_length=255)
    role: Role | None = None
    service_id: int | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    action: str
    actor_login: str
    object_type: str | None
    object_id: int | None
    detail: dict
    ip_address: str | None


class SystemOut(BaseModel):
    llm_provider: str
    ekp_rules: int
    response_deadline_seconds: int
    users_total: int
    users_blocked: int
    scenarios_total: int
    scenarios_approved: int
    sessions_total: int
    attempts_total: int
    audit_events: int


def _running_session_of(db: Session, user: User) -> TrainingSession | None:
    """Идущее занятие, в котором участвует пользователь, иначе None.

    Техническое задание ограничивает администратора в прямом вмешательстве
    в учебный процесс: «администратор не может менять оценки или сценарии
    во время активного занятия». Проверка адресная, а не «идёт хоть
    какое-нибудь занятие»: правка учётной записи постороннего сотрудника
    идущему занятию не мешает, а запрещать сверх требования — значит
    мешать администратору делать свою работу.

    Участие определяется и составом занятия, и выданными карточками.
    Карточка учитывается отдельно, потому что она и есть след занятия
    у обучающегося: работа уже начата, чем бы ни был заполнен состав.
    """
    return db.scalar(
        select(TrainingSession)
        .where(
            TrainingSession.state == SessionState.ACTIVE,
            or_(
                TrainingSession.teacher_id == user.id,
                TrainingSession.students.any(User.id == user.id),
                TrainingSession.attempts.any(Attempt.student_id == user.id),
            ),
        )
        .limit(1)
    )


def _out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        login=user.login,
        full_name=user.full_name,
        role=str(user.role),
        is_active=user.is_active,
        service_id=user.service_id,
        service_name=user.service.name if user.service else None,
        created_at=user.created_at,
    )


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_session), admin: User = Depends(require_admin)
) -> list[UserOut]:
    users = db.scalars(select(User).order_by(User.id)).all()
    return [_out(u) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserIn,
    request: Request,
    db: Session = Depends(get_session),
    admin: User = Depends(require_admin),
) -> UserOut:
    if db.scalar(select(User).where(User.login == payload.login)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой логин уже занят")
    service = _service_or_none(db, payload.service_id)

    user = User(
        login=payload.login,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        service=service,
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        AuditAction.USER_CREATED,
        actor=admin,
        object_type="user",
        object_id=user.id,
        detail={"login": user.login, "role": str(user.role)},
        request=request,
    )
    db.commit()
    return _out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserPatch,
    request: Request,
    db: Session = Depends(get_session),
    admin: User = Depends(require_admin),
) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Учётная запись не найдена")

    data = payload.model_dump(exclude_unset=True)
    if "is_active" in data and data["is_active"] is False and user.id == admin.id:
        # Иначе администратор запирает сам себя и войти станет некому.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Нельзя заблокировать собственную учётную запись"
        )

    # Роль и служба — это состав занятия: роль решает, чьи карточки человек
    # видит, служба — от имени какой ДДС он их отрабатывает. Преподавателю
    # состав после запуска уже закрыт (см. teacher.update_session), и было бы
    # странно, если бы администратор менял его в обход. Блокировка,
    # разблокировка, смена пароля и правка ФИО остаются доступными: первые
    # три прямо вменены администратору как мера безопасности, последняя
    # учебного процесса не касается.
    if ("role" in data and data["role"] != user.role) or (
        "service_id" in data and data["service_id"] != user.service_id
    ):
        running = _running_session_of(db, user)
        if running is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Идёт занятие «{running.title}»: роль и служба его участника "
                "меняются только после завершения занятия",
            )

    changed: dict = {}
    if password := data.pop("password", None):
        user.hashed_password = hash_password(password)
        audit.record(
            db,
            AuditAction.PASSWORD_CHANGED,
            actor=admin,
            object_type="user",
            object_id=user.id,
            detail={"login": user.login},
            request=request,
        )
    if "service_id" in data:
        user.service = _service_or_none(db, data.pop("service_id"))
        changed["service"] = user.service.name if user.service else None
    if "is_active" in data:
        active = data.pop("is_active")
        user.is_active = active
        audit.record(
            db,
            AuditAction.USER_UNBLOCKED if active else AuditAction.USER_BLOCKED,
            actor=admin,
            object_type="user",
            object_id=user.id,
            detail={"login": user.login},
            request=request,
        )
    for key, value in data.items():
        setattr(user, key, value)
        changed[key] = str(value)

    if changed:
        audit.record(
            db,
            AuditAction.USER_UPDATED,
            actor=admin,
            object_type="user",
            object_id=user.id,
            detail={"login": user.login, **changed},
            request=request,
        )
    db.commit()
    return _out(user)


def _service_or_none(db: Session, service_id: int | None) -> DispatchService | None:
    if service_id is None:
        return None
    service = db.get(DispatchService, service_id)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Служба не найдена")
    return service


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    ekp_name: str | None = None


@router.get("/services", response_model=list[ServiceOut])
def services(
    db: Session = Depends(get_session), admin: User = Depends(require_admin)
) -> list[ServiceOut]:
    """Справочник служб — нужен при назначении службы обучающемуся."""
    rows = db.scalars(select(DispatchService).order_by(DispatchService.name)).all()
    return [ServiceOut.model_validate(s) for s in rows]


@router.get("/audit", response_model=list[AuditOut])
def audit_log(
    action: str | None = None,
    actor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_session),
    admin: User = Depends(require_admin),
) -> list[AuditOut]:
    query = select(AuditEvent).order_by(AuditEvent.at.desc(), AuditEvent.id.desc())
    if action:
        query = query.where(AuditEvent.action == action)
    if actor:
        query = query.where(AuditEvent.actor_login == actor)
    return [
        AuditOut.model_validate(e) for e in db.scalars(query.limit(min(limit, 500))).all()
    ]


@router.get("/audit/actions", response_model=list[str])
def audit_actions(admin: User = Depends(require_admin)) -> list[str]:
    return [str(a) for a in AuditAction]


@router.get("/system", response_model=SystemOut)
def system(
    db: Session = Depends(get_session), admin: User = Depends(require_admin)
) -> SystemOut:
    settings = get_settings()

    def count(model, *where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    return SystemOut(
        llm_provider=settings.llm_provider,
        ekp_rules=len(get_ekp()),
        response_deadline_seconds=settings.default_response_deadline_seconds,
        users_total=count(User),
        users_blocked=count(User, User.is_active.is_(False)),
        scenarios_total=count(Scenario),
        scenarios_approved=count(Scenario, Scenario.approved_at.is_not(None)),
        sessions_total=count(TrainingSession),
        attempts_total=count(Attempt),
        audit_events=count(AuditEvent),
    )
