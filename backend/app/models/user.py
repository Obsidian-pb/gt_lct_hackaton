from enum import StrEnum

from sqlalchemy import Boolean
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Role(StrEnum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


class DispatchService(Base, TimestampMixin):
    """Служба — участник информационного взаимодействия системы-112.

    Справочник наполняется из ЕКП: обучающийся работает от имени конкретной
    службы, и от этого зависит, какие карточки попадают в его ленту и какие
    происшествия для него профильные.
    """

    __tablename__ = "dispatch_service"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    # Название этой же службы в классификаторе. Отличается от отображаемого:
    # районные ДДС проходят в ЕКП как «Территориальные ОИВ», а не поимённо.
    # По нему определяется, профильное ли происшествие и подсвечивать ли
    # блок службы в списке оповещения.
    ekp_name: Mapped[str | None] = mapped_column(String(255))
    # Работает через АРМ-112 или через интеграцию информационных систем.
    uses_arm112: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def classifier_name(self) -> str:
        return self.ekp_name or self.name

    users: Mapped[list["User"]] = relationship(back_populates="service")


class User(Base, TimestampMixin):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(SAEnum(Role, native_enum=False, length=32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    service_id: Mapped[int | None] = mapped_column(ForeignKey("dispatch_service.id"))
    service: Mapped[DispatchService | None] = relationship(back_populates="users")
