"""Выгрузка отчёта о занятии в CSV и PDF.

Оба формата названы в техническом задании: CSV — для выгрузки отчётов
и статистики, PDF — для формирования документов. Содержимое отчёта уже
посчитано в services/report.py, здесь оно только раскладывается по форматам,
поэтому цифры в выгрузке и на экране расходиться не могут.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.base import as_utc
from app.models.training import SessionState, TrainingMode
from app.services.report import SessionReport
from app.services.violations import kind_of

# Время в документе — московское: комплекс учебный, занятие проводится
# по местному времени, а в базе всё хранится в UTC. Смещение задано числом,
# а не zoneinfo: Москва с 2014 года живёт на постоянном UTC+3, зато zoneinfo
# на Windows требует отдельного пакета tzdata, которого в зависимостях нет.
MOSCOW = timezone(timedelta(hours=3))

FONT_NAME = "PTSans"
FONT_FILE = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "PTSans-Regular.ttf"

MODE_LABELS: dict[TrainingMode, str] = {
    TrainingMode.DISPATCHER: "Диспетчер ДДС",
    TrainingMode.OPERATOR: "Оператор Службы 112",
}

STATE_LABELS: dict[SessionState, str] = {
    SessionState.DRAFT: "Черновик",
    SessionState.ACTIVE: "Идёт",
    SessionState.FINISHED: "Завершено",
}

STUDENT_COLUMNS = (
    "Обучающийся",
    "Карточек",
    "Завершено",
    "Средний балл",
    "Просрочек норматива",
    "Нарушений",
)

VIOLATION_COLUMNS = ("Код", "Нарушение", "Тяжесть", "Случаев", "Доля завершённых, %")

REPEAT_COLUMNS = ("Обучающийся", "Карточка", "Первая попытка", "После повтора", "Итог")

DASH = "—"


def _moment(value: datetime | None) -> str:
    return as_utc(value).astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M") if value else DASH


def _number(value: float, digits: int = 1) -> str:
    """Число с десятичной запятой.

    Excel в русской локали считает «87.3» текстом: колонка перестаёт
    суммироваться и сортируется по алфавиту. Разделитель полей — точка
    с запятой, поэтому запятая внутри числа ни с чем не конфликтует.
    """
    return f"{value:.{digits}f}".replace(".", ",")


def _score(value: float) -> str:
    """Балл по стобалльной шкале — так он показан преподавателю на экране."""
    return _number(value * 100)


def _share(part: int, whole: int) -> str:
    return _number(100 * part / whole) if whole else _number(0)


def _student_rows(report: SessionReport) -> list[list[str]]:
    return [
        [
            student.student_name,
            str(student.attempts),
            str(student.finished),
            _score(student.average_score) if student.finished else DASH,
            str(student.overdue),
            str(sum(student.violations.values())),
        ]
        for student in report.students
    ]


def _summary_rows(report: SessionReport) -> list[list[str]]:
    return [
        ["Карточек выдано", str(report.total_attempts)],
        ["Карточек завершено", str(report.finished_attempts)],
        [
            "Средний балл",
            _score(report.average_score) if report.finished_attempts else DASH,
        ],
        [
            "Среднее время до взятия в работу, с",
            _number(report.average_response_seconds)
            if report.average_response_seconds is not None
            else DASH,
        ],
        ["Доля просрочек норматива, %", _number(report.overdue_share * 100)],
        ["Замечаний к грамматике", str(report.grammar_issues)],
        # Повторы — отдельными строками: в «выдано» и «завершено» выше они
        # не входят, там только первый проход, по которому ставится зачёт.
        ["Повторных выдач", str(report.repeats_issued)],
        [
            "Исправились после повтора",
            f"{report.repeats_fixed} из {report.repeats_finished}"
            if report.repeats_finished
            else DASH,
        ],
    ]


def _repeat_verdict(fixed: bool | None) -> str:
    if fixed is None:
        return "не завершён"
    return "исправился" if fixed else "не исправился"


def _repeat_rows(report: SessionReport) -> list[list[str]]:
    return [
        [
            student.student_name,
            repeat.scenario_title,
            _score(repeat.first_score) if repeat.first_score is not None else DASH,
            _score(repeat.repeat_score) if repeat.repeat_score is not None else DASH,
            _repeat_verdict(repeat.fixed),
        ]
        for student in report.students
        for repeat in student.repeats
    ]


def _violation_rows(report: SessionReport) -> list[list[str]]:
    rows = []
    for code, count in report.violations.most_common():
        kind = kind_of(code)
        rows.append(
            [
                code,
                kind.title,
                str(kind.severity),
                str(count),
                _share(count, report.finished_attempts),
            ]
        )
    return rows


def _session_rows(report: SessionReport) -> list[list[str]]:
    session = report.session
    return [
        ["Занятие", session.title],
        ["Режим обучения", MODE_LABELS[session.mode]],
        ["Состояние", STATE_LABELS[session.state]],
        ["Начало", _moment(session.started_at)],
        ["Окончание", _moment(session.finished_at)],
        ["Норматив взятия в работу, с", str(session.pickup_deadline_seconds)],
        ["Норматив обработки, с", str(session.handling_deadline_seconds)],
    ]


def build_csv(report: SessionReport) -> bytes:
    """Отчёт в CSV: строки по обучающимся и сводка по занятию."""
    buffer = io.StringIO()
    # Точка с запятой и CRLF — то, что Excel открывает двойным щелчком
    # без мастера импорта.
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")

    writer.writerow(["Отчёт о практическом занятии"])
    writer.writerows(_session_rows(report))

    writer.writerow([])
    writer.writerow(list(STUDENT_COLUMNS))
    writer.writerows(_student_rows(report))

    writer.writerow([])
    writer.writerow(["Итоги занятия"])
    writer.writerows(_summary_rows(report))

    if report.violations:
        writer.writerow([])
        writer.writerow(["Типичные нарушения"])
        writer.writerow(list(VIOLATION_COLUMNS))
        writer.writerows(_violation_rows(report))

    if report.repeats_issued:
        writer.writerow([])
        writer.writerow(["Повторные выдачи проваленных карточек"])
        writer.writerow(list(REPEAT_COLUMNS))
        writer.writerows(_repeat_rows(report))

    writer.writerow([])
    writer.writerow(["Выводы по группе"])
    writer.writerows([insight] for insight in report.insights)

    # UTF-8 с BOM: без него Excel на Windows читает файл в кодировке системы
    # и вместо кириллицы показывает кракозябры.
    return buffer.getvalue().encode("utf-8-sig")


def _ensure_font() -> None:
    """Подключает шрифт с кириллицей.

    Базовые шрифты PDF кириллицу не содержат: без встроенного шрифта отчёт
    открылся бы пустыми квадратами вместо текста. PT Sans лежит рядом с кодом
    (лицензия SIL OFL, файл OFL.txt) — рассчитывать на системные шрифты нельзя,
    комплекс ставится и в минимальный контейнер, где их нет вовсе.
    """
    if FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_FILE)))


@lru_cache(maxsize=1)
def _styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "title", fontName=FONT_NAME, fontSize=16, leading=20, spaceAfter=2 * mm
        ),
        "hint": ParagraphStyle(
            "hint",
            fontName=FONT_NAME,
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#5b6472"),
            spaceAfter=4 * mm,
        ),
        "heading": ParagraphStyle(
            "heading",
            fontName=FONT_NAME,
            fontSize=12,
            leading=15,
            spaceBefore=5 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle("body", fontName=FONT_NAME, fontSize=9.5, leading=13),
        "cell": ParagraphStyle("cell", fontName=FONT_NAME, fontSize=8.5, leading=11),
        "head": ParagraphStyle(
            "head",
            fontName=FONT_NAME,
            fontSize=8.5,
            leading=10,
            textColor=colors.HexColor("#3a424f"),
        ),
    }


def _cell(text: str, style: str = "cell") -> Paragraph:
    """Ячейка абзацем: длинные названия переносятся, а не налезают на соседей."""
    return Paragraph(text, _styles()[style])


def _table(rows: list[list], widths: list[float], columns: tuple[str, ...] = ()) -> Table:
    body = [[_cell(name, "head") for name in columns]] + rows if columns else rows
    table = Table(body, colWidths=widths, repeatRows=1 if columns else 0, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8cdd6")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if columns:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f6")))
    table.setStyle(TableStyle(style))
    return table


def _footer(canvas, document) -> None:
    """Штамп внизу страницы: когда и чем сформирован документ."""
    canvas.saveState()
    canvas.setFont(FONT_NAME, 7.5)
    canvas.setFillColor(colors.HexColor("#8a919c"))
    stamp = datetime.now(MOSCOW).strftime("%d.%m.%Y %H:%M")
    canvas.drawString(
        20 * mm, 12 * mm, f"Сформировано учебным комплексом Системы-112, {stamp} (МСК)"
    )
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Стр. {document.page}")
    canvas.restoreState()


def build_pdf(report: SessionReport) -> bytes:
    """Отчёт в PDF — документ, который преподаватель подшивает к занятию."""
    _ensure_font()
    styles = _styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title=f"Отчёт по занятию №{report.session.id}",
        author="Учебный комплекс Системы-112",
    )
    width = document.width

    story: list = [
        Paragraph("Отчёт о практическом занятии", styles["title"]),
        Paragraph(
            "Действия обучающихся, замечания, время обработки карточки "
            "и отклонение от норматива.",
            styles["hint"],
        ),
        _table(_session_rows(report), [60 * mm, width - 60 * mm]),
        Paragraph("Итоги занятия", styles["heading"]),
        _table(_summary_rows(report), [80 * mm, width - 80 * mm]),
        Paragraph("Обучающиеся", styles["heading"]),
        _table(
            [[_cell(row[0])] + row[1:] for row in _student_rows(report)],
            [width - 116 * mm, 20 * mm, 22 * mm, 24 * mm, 26 * mm, 24 * mm],
            STUDENT_COLUMNS,
        ),
    ]

    if report.violations:
        story.append(Paragraph("Типичные нарушения", styles["heading"]))
        story.append(
            _table(
                [
                    [row[0], _cell(row[1]), row[2], row[3], row[4]]
                    for row in _violation_rows(report)
                ],
                [14 * mm, width - 88 * mm, 28 * mm, 20 * mm, 26 * mm],
                VIOLATION_COLUMNS,
            )
        )

    if report.repeats_issued:
        story.append(Paragraph("Повторные выдачи проваленных карточек", styles["heading"]))
        story.append(
            _table(
                [
                    [_cell(row[0]), _cell(row[1]), row[2], row[3], row[4]]
                    for row in _repeat_rows(report)
                ],
                [50 * mm, width - 128 * mm, 26 * mm, 26 * mm, 26 * mm],
                REPEAT_COLUMNS,
            )
        )

    # Заголовок «Выводы» держится вместе с первым выводом: заголовок, брошенный
    # внизу страницы без текста, читается как обрыв документа.
    insights = [
        Paragraph(f"{number}. {insight}", styles["body"])
        for number, insight in enumerate(report.insights, start=1)
    ]
    story.append(
        KeepTogether([Paragraph("Выводы по группе", styles["heading"]), insights[0]])
    )
    for insight in insights[1:]:
        story.append(Spacer(1, 2 * mm))
        story.append(insight)

    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def file_stem(report: SessionReport) -> str:
    """Имя файла без расширения: номер занятия и дата, только латиница."""
    session = report.session
    moment = session.finished_at or session.started_at
    day = (as_utc(moment).astimezone(MOSCOW) if moment else datetime.now(MOSCOW)).strftime(
        "%Y-%m-%d"
    )
    return f"report-session-{session.id}-{day}"


def content_disposition(report: SessionReport, extension: str) -> str:
    """Заголовок вложения с русским именем файла и латинским запасным.

    Кириллица в filename= ломается в части браузеров — от «?????.pdf» до
    отброшенного заголовка, — поэтому основное имя латиницей, а читаемое
    русское передаётся в filename* по RFC 5987.
    """
    human = f"Отчёт по занятию №{report.session.id}.{extension}"
    return (
        f'attachment; filename="{file_stem(report)}.{extension}"; '
        f"filename*=UTF-8''{quote(human)}"
    )
