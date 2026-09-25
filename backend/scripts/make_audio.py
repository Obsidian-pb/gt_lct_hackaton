"""Озвучивание учебных вызовов в звуковые файлы.

Браузерный синтез оказался ненадёжен: в Firefox после отмены речи движок
остаётся в нерабочем состоянии до перезагрузки страницы, и это не лечится
со стороны приложения. Поэтому звук готовится заранее, а браузер лишь
проигрывает готовый файл — одинаково во всех браузерах.

Побочно закрывается требование технического задания к форматам данных:
MP3 для аудиозаписей учебных вызовов.

Запускается на macOS: синтез выполняет системный голос Milena. Файлы
складываются в раздачу фронтенда и попадают в образ при сборке.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
TICKETS = BACKEND_DIR / "data" / "tickets.json"
OUT_DIR = BACKEND_DIR.parent / "frontend" / "public" / "audio"

VOICE = "Milena"

# Сокращения синтезатор читает по буквам: «ул точка» вместо «улица».
ABBREVIATIONS = [
    (r"(^|[\s(«])ул\.", r"\1улица"),
    (r"(^|[\s(«])д\.", r"\1дом"),
    (r"(^|[\s(«])корп\.", r"\1корпус"),
    (r"(^|[\s(«])под\.", r"\1подъезд"),
    (r"(^|[\s(«])кв\.", r"\1квартира"),
    (r"(^|[\s(«])эт\.", r"\1этаж"),
    (r"(^|[\s(«])стр\.", r"\1строение"),
    (r"(^|[\s(«])ш\.", r"\1шоссе"),
    (r"(^|[\s(«])пр-т(?=[\s.,]|$)", r"\1проспект"),
    (r"(^|[\s(«])а/м(?=[\s.,]|$)", r"\1автомашина"),
    (r"(^|[\s(«])д/р(?=[\s.,]|$)", r"\1дата рождения"),
    (r"(^|[\s(«])б/п(?=[\s.,]|$)", r"\1без пострадавших"),
    (r"(^|[\s(«])б/р(?=[\s.,]|$)", r"\1без разлития"),
    (r"(^|[\s(«])г\.(?=\s*[А-ЯЁ])", r"\1город "),
    # Найдены прогоном по всем 96 билетам: всё, что синтезатор читал по буквам.
    (r"(^|[\s(«])обл\.", r"\1область"),
    (r"(^|[\s(«])пос\.", r"\1посёлок"),
    (r"(^|[\s(«])дер\.", r"\1деревня"),
    (r"(^|[\s(«])мкр\.", r"\1микрорайон"),
    (r"(^|[\s(«])пл\.", r"\1площадь"),
    (r"(^|[\s(«])п\.(?=\s*[А-ЯЁ])", r"\1посёлок "),
    (r"(^|[\s(«])р\.(?=\s*[А-ЯЁ])", r"\1река "),
    (r"(около|у|возле|от|до|рядом с)\s+ст\.", r"\1 станции"),
    (r"(^|[\s(«])ст\.(?=\s*[А-ЯЁ])", r"\1станция "),
    (r"(^|[\s(«])ж/д(?=[\s.,]|$)", r"\1железнодорожная"),
    (r"(^|[\s(«])с/п(?=[\s.,]|$)", r"\1сельское поселение"),
    (r"(^|[\s(«])ч/дом", r"\1частный дом"),
    (r"(^|[\s(«])(?i:б/п)(?=[\s.,]|$)", r"\1без пострадавших"),
    (r"(^|[\s(«])(?i:б/р)(?=[\s.,]|$)", r"\1без разлития"),
    (r"(^|[\s(«])А/Д(?=[\s.,]|$)", r"\1давление"),
    (r"(^|[\s(«])авт\.", r"\1автобусной "),
    (r"(^|[\s(«])гос\.", r"\1государственный "),
    (r"(^|[\s(«])тел\.", r"\1телефон"),
    (r"(^|[\s(«])треб\.", r"\1требуется"),
    (r"(^|[\s(«])ТТК(?=[\s.,]|$)", r"\1тэ тэ ка"),
    (r"(^|[\s(«])Ген\.", r"\1Генерала"),
    (r"(^|[\s(«])т\.\s?к\.", r"\1так как"),
    (r"SHELL", "Шелл"),
    (r"WHEITE", "Уайт"),
    (r"(^|[\s(«])03(?=[\s.,]|$)", r"\1ноль три"),
]


def speakable(text: str) -> str:
    """Готовит текст к произнесению.

    Телефон диктуется по цифрам: слитное «девятьсот шестнадцать миллионов»
    на слух бесполезно, а оператор записывает номер с голоса.
    """
    result = re.sub(
        r"(\d[\d\s-]{7,}\d)",
        lambda m: " ".join(re.sub(r"[\s-]", "", m.group(1))),
        text,
    )
    for pattern, replacement in ABBREVIATIONS:
        result = re.sub(pattern, replacement, result)
    return result


def synthesize(text: str, target: Path) -> None:
    aiff = target.with_suffix(".aiff")
    subprocess.run(
        ["say", "-v", VOICE, "-r", "185", "-o", str(aiff), text],
        check=True,
        capture_output=True,
    )
    # Моно и невысокий поток: речь, а не музыка — качество не страдает,
    # а файлы остаются лёгкими для репозитория и для раздачи.
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
         "-ac", "1", "-b:a", "64k", str(target)],
        check=True,
        capture_output=True,
    )
    aiff.unlink(missing_ok=True)


def main(force: bool) -> None:
    if not shutil.which("say") or not shutil.which("ffmpeg"):
        print("Нужны say (macOS) и ffmpeg.", file=sys.stderr)
        raise SystemExit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.loads(TICKETS.read_text(encoding="utf-8"))

    made = skipped = 0
    for ticket in payload["tickets"]:
        for call in ticket["calls"]:
            target = OUT_DIR / f"ticket-{ticket['ticket']}-{call['no']}.mp3"
            if target.exists() and not force:
                skipped += 1
                continue
            # Заявитель диктует адрес следом за описанием — как в разговоре.
            text = speakable(f"{call['situation']}. Адрес: {call['address']}")
            synthesize(text, target)
            made += 1
            print(f"  {target.name}  {target.stat().st_size // 1024} КБ")

    total = sum(f.stat().st_size for f in OUT_DIR.glob("*.mp3"))
    print(f"\nозвучено {made}, пропущено {skipped}, всего {total // 1024} КБ")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Озвучивание вызовов в MP3")
    cli.add_argument("--force", action="store_true", help="переозвучить уже готовые")
    main(cli.parse_args().force)
