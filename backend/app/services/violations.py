"""Каталог нарушений и критериев оценки работы диспетчера ДДС.

Источник — памятка ГБУ «Система 112»: раздел «Правила проставления статусов
реагирования» (4 критерия) и «Примеры нарушений при обработке карточки
происшествия» (7 типов). Коды сохраняют нумерацию памятки, чтобы отчёт
преподавателя можно было сверить с первоисточником.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Criterion(StrEnum):
    """Критерии правильности из раздела «Правила проставления статусов»."""

    ACTUAL_MATCH = "Соответствие фактическому статусу заявки"
    COMPETENCE = "Соответствие компетенции службы"
    TIMELINESS = "Своевременность"
    COMPLETENESS = "Полнота информации"


class Severity(StrEnum):
    CRITICAL = "критическое"
    MAJOR = "существенное"
    MINOR = "замечание"


@dataclass(frozen=True)
class ViolationKind:
    code: str
    title: str
    criterion: Criterion
    severity: Severity
    # Пример из памятки — показывается обучающемуся в разборе ошибок.
    example: str


CATALOG: dict[str, ViolationKind] = {
    v.code: v
    for v in (
        ViolationKind(
            "V1",
            "Отсутствует статус реагирования",
            Criterion.TIMELINESS,
            Severity.CRITICAL,
            "Карточка переходит в статус «Не оповещено» и попадает в отдел контроля.",
        ),
        ViolationKind(
            "V2",
            "Статус реагирования не соответствует фактическому",
            Criterion.ACTUAL_MATCH,
            Severity.CRITICAL,
            "Повреждение дорожного покрытия: проставлено «Принята: не обслуживаем территорию», "
            "следовало «Не принята: не обслуживаем территорию».",
        ),
        ViolationKind(
            "V3",
            "Отказ от реагирования на профильное происшествие",
            Criterion.COMPETENCE,
            Severity.CRITICAL,
            "Посторонние граждане в подвале жилого дома: проставлено «Не принята» без "
            "комментариев, после разъяснений информация принята.",
        ),
        ViolationKind(
            "V4",
            "Нет комментария к статусу «Не принята» или «Отказ от выполнения работ»",
            Criterion.COMPLETENESS,
            Severity.MAJOR,
            "Сработала пожарная сигнализация: дом обслуживает УК «ПИК», информация передана "
            "в их диспетчерскую — это следовало указать в комментарии.",
        ),
        ViolationKind(
            "V5",
            "Неполный комментарий",
            Criterion.COMPLETENESS,
            Severity.MAJOR,
            "Застревание в лифте: «Не принята: не обслуживаем», но не указано, что информация "
            "передана в диспетчерскую «Практика».",
        ),
        ViolationKind(
            "V6",
            "Отсутствуют статусы хода выполнения работ",
            Criterion.COMPLETENESS,
            Severity.MINOR,
            "Прорыв трубы с горячей водой: работы велись, но статусы хода работ и комментарии "
            "в карточку не вносились, заявители жаловались на бездействие служб.",
        ),
        ViolationKind(
            "V7",
            "Нарушена последовательность статусов",
            Criterion.ACTUAL_MATCH,
            Severity.MAJOR,
            "Статусы реагирования выбираются только последовательно.",
        ),
    )
}


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str
    # Чем подтверждается: тайминг, номер события, фрагмент комментария.
    evidence: str | None = None

    @property
    def kind(self) -> ViolationKind:
        return CATALOG[self.code]
