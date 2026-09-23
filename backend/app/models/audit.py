from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, Text, func
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
    # Обратная связь дописывается к уже выставленной оценке, то есть меняет
    # результат обучения, — а его по ТЗ нельзя менять без записи в журнале.
    # Новый элемент перечисления схему не трогает: в базе лежит VARCHAR(48)
    # без ограничения на значения, миграция для него не нужна.
    FEEDBACK_LEFT = "Оставлено примечание к работе"
    # Справочная база. Загрузка учебных материалов — действие пользователя,
    # а ТЗ требует аудита всех действий; публикация к тому же меняет то,
    # что видят обучающиеся, а удаление лишает их материала.
    MATERIAL_CREATED = "Создан учебный материал"
    MATERIAL_UPDATED = "Изменён учебный материал"
    MATERIAL_FILE_UPLOADED = "Загружен файл учебного материала"
    MATERIAL_PUBLISHED = "Учебный материал опубликован"
    MATERIAL_UNPUBLISHED = "Учебный материал снят с публикации"
    MATERIAL_DELETED = "Удалён учебный материал"
    # Учебные группы: изменение состава решает, кто получит карточки
    # на следующем занятии, — это распределение доступа к обучению.
    GROUP_CREATED = "Создана учебная группа"
    GROUP_UPDATED = "Изменена учебная группа"
    GROUP_DELETED = "Удалена учебная группа"
    # Конфигурация комплекса. Смена провайдера решает, куда уходят тексты
    # обучающихся, а глубина хранения журнала — как долго вообще существуют
    # сами записи аудита. Настройка без следа в журнале означала бы, что
    # журнал можно обойти, изменив его же параметры.
    SETTINGS_LLM_UPDATED = "Изменены настройки языковой модели"
    SETTINGS_LLM_KEY_CLEARED = "Удалён ключ доступа к языковой модели"
    SETTINGS_LOGGING_UPDATED = "Изменены параметры журналирования"
    # Редакции классификатора. Включённая редакция определяет эталон всех
    # занятий, которые будут созданы после, — это и есть импорт обновлений
    # учебных материалов из ТЗ, и его след обязан остаться в журнале.
    CLASSIFIER_UPLOADED = "Загружена редакция классификатора"
    CLASSIFIER_ACTIVATED = "Включена редакция классификатора"
    CLASSIFIER_BUILTIN_RESTORED = "Возвращена встроенная редакция классификатора"


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


class ErrorEvent(Base):
    """Сбой в работе комплекса.

    Техническое задание требует от администратора «формировать отчёты
    об ошибках и сбоях», а на учебном комплексе он видит только браузер:
    журналы контейнеров ему недоступны. Поэтому необработанные ошибки
    приложения складываются в базу и показываются в кабинете.

    Хранится отдельно от журнала аудита: аудит отвечает на вопрос «кто что
    сделал» и не удаляется полгода, а список сбоев — техническая сводка,
    которую чистят по мере устранения.
    """

    __tablename__ = "error_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # Куда пришёл запрос, на котором всё сломалось.
    path: Mapped[str | None] = mapped_column(String(255))
    method: Mapped[str | None] = mapped_column(String(10))
    # Тип исключения и сообщение — по ним сбои группируются.
    kind: Mapped[str] = mapped_column(String(128), index=True)
    message: Mapped[str] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text)
    actor_login: Mapped[str | None] = mapped_column(String(150))


class SystemSetting(Base):
    """Настройка комплекса, заданная администратором из интерфейса.

    Пара «ключ — значение», а не колонки на каждую настройку: иначе любая
    новая настройка требовала бы миграции, а их приходится согласовывать
    между всеми, кто правит систему одновременно.

    Значение из базы главнее переменной окружения: переменные задают
    начальное состояние при первом запуске, дальше комплексом управляет
    администратор, у которого доступа к серверу нет.

    Секреты (ключ доступа к языковой модели) хранятся здесь же и наружу
    не отдаются никогда — только признак того, что значение задано.
    """

    __tablename__ = "system_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    updated_by: Mapped[User | None] = relationship()
