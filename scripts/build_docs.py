"""Сборка сопроводительной документации в .docx и .pdf.

Техническое задание требует документацию в .docx или .pdf, но вести её
в этих форматах неудобно: бинарный файл не читается в истории изменений
и порождает конфликты при правке. Поэтому документ пишется в Markdown,
а в требуемые форматы собирается этой командой перед сдачей.

Сверка с техническим заданием подшивается приложением, а не переписывается
в документ: иначе два перечня ограничений разойдутся, и в сдаваемом файле
останется устаревший.

Требуется pandoc. Для PDF годится либо XeLaTeX, либо LibreOffice —
что найдётся; оба справляются с кириллицей.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SOURCE = DOCS / "documentation.md"
APPENDIX = DOCS / "tz-coverage.md"
BUILD = DOCS / "build"

APPENDIX_TITLE = "Приложение А. Сверка решения с техническим заданием"


def assemble() -> str:
    """Склеивает документ с приложением, сдвигая его заголовки на уровень ниже."""
    text = SOURCE.read_text(encoding="utf-8")
    extra = APPENDIX.read_text(encoding="utf-8")

    # Заголовок первого уровня у приложения заменяется на его название,
    # остальные опускаются на уровень: в сшитом документе приложение —
    # это раздел, а не второй самостоятельный документ.
    lines = []
    for line in extra.splitlines():
        if line.startswith("# "):
            continue
        lines.append("#" + line if line.startswith("#") else line)
    body = "\n".join(lines)

    return f"{text}\n\n---\n\n# {APPENDIX_TITLE}\n\n{body}\n"


def to_docx(source: Path, target: Path) -> None:
    subprocess.run(
        [
            "pandoc", str(source), "-o", str(target),
            "--from", "gfm",
            "--toc", "--toc-depth=2",
            # Нумерация разделов в исходнике проставлена вручную, поэтому
            # автоматическую не включаем — иначе получится «1. 1. Назначение».
            "--metadata", "lang=ru-RU",
        ],
        check=True,
        capture_output=True,
    )


def to_pdf(markdown: Path, docx: Path, target: Path) -> str:
    """PDF собирается через XeLaTeX, а при его отсутствии — из .docx."""
    if shutil.which("xelatex"):
        subprocess.run(
            [
                "pandoc", str(markdown), "-o", str(target),
                "--from", "gfm",
                "--pdf-engine=xelatex",
                "--toc", "--toc-depth=2",
                "--metadata", "lang=ru-RU",
                # Шрифт с кириллицей обязателен: со шрифтом по умолчанию
                # XeLaTeX выдаёт пустые места вместо русских букв.
                "-V", "mainfont=Times New Roman",
                "-V", "monofont=Menlo",
                "-V", "geometry:margin=2cm",
            ],
            check=True,
            capture_output=True,
        )
        return "xelatex"

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(target.parent), str(docx)],
            check=True,
            capture_output=True,
        )
        produced = target.parent / (docx.stem + ".pdf")
        if produced != target:
            produced.replace(target)
        return "libreoffice"

    raise SystemExit(
        "Для PDF нужен XeLaTeX или LibreOffice. Файл .docx собран, "
        "PDF можно получить из него любым конвертером."
    )


def main(keep_markdown: bool) -> None:
    if not shutil.which("pandoc"):
        raise SystemExit("Нужен pandoc: brew install pandoc / apt install pandoc")
    for path in (SOURCE, APPENDIX):
        if not path.exists():
            raise SystemExit(f"Не найден исходник: {path}")

    BUILD.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    name = f"Тренажёр-Системы-112-документация-{stamp}"

    merged = BUILD / f"{name}.md"
    merged.write_text(assemble(), encoding="utf-8")

    docx = BUILD / f"{name}.docx"
    pdf = BUILD / f"{name}.pdf"
    to_docx(merged, docx)
    engine = to_pdf(merged, docx, pdf)

    if not keep_markdown:
        merged.unlink()

    for path in (docx, pdf):
        print(f"  {path.relative_to(ROOT)}  {path.stat().st_size // 1024} КБ")
    print(f"PDF собран через {engine}.")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Сборка сопроводительной документации")
    cli.add_argument(
        "--keep-markdown", action="store_true", help="оставить склеенный markdown"
    )
    main(cli.parse_args().keep_markdown)
