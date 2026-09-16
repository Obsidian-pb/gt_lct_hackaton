from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.user import User


class AuditAction(StrEnum):
    """Значимые события, которые требует протоколировать техническое задание.

    Перечисление закрытое: журнал должен быть пригоден для выборки и подсчёта,
    а произвольные строки превратили бы его в свалку.
    """

    LOGIN = "Вход в систему"
    LOGIN_FAILED = "Неудачная попытка входа"
    USER_CREATED = "Создана учётная запись"
    USER_UPDATED = "Изменена учётная запись"
    USER_BLOCKED = "Учётная запись заблокирована"
    USER_UNBLOCKED = "Учётная запись разблокирована"
    PASSWORD_CHANGED = "Изменён пароль"
    SCENARIO_GENERATED = "Сформированы учебные сценарии"
    SCENARIO_APPROVED = "Сценарий утверждён"
    SCENARIO_CORRECTED = "Сценарий переформирован по замечанию"
    SCENARIO_DELETED = "Сценарий удалён"


class AuditEvent(Base):
    """Запись журнала аудита.

    Логин исполнителя дублируется строкой: учётную запись могут удалить,
    а журнал безопасности по ТЗ хранится не менее шести месяцев и должен
    оставаться читаемым.
    """

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, native_enum=False, length=48), index=True
    )

    actor_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    actor: Mapped[User | None] = relationship()
    actor_login: Mapped[str] = mapped_column(String(150))

    object_type: Mapped[str | None] = mapped_column(String(64))
    object_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))
