"""Озвучивание учебных вызовов разными голосами — по полу заявителя.

Один голос на все 96 вызовов приучает к одному тембру и темпу, а в смене
звонят мужчины и женщины, быстро и медленно, по плохой связи. Поэтому
каждый вызов озвучивается несколькими голосами пола заявителя, а при
выдаче обучающемуся вариант выбирается случайно и закрепляется за его
попыткой: при повторном прослушивании голос тот же, у соседа — другой.

Синтез выполняется только здесь, при сборке. В комплект и в образ уходят
готовые MP3 — у заказчика нет ни синтезатора, ни голосовых моделей.

Голоса (все работают локально, без сети):
  мужские — Piper: denis, dmitri, ruslan; Silero: eugene; macOS: Юрий (улучшенный)
  женские — Silero: baya, xenia; macOS: Катя (улучшенный), Милена (улучшенный), Милена

Запуск (на Mac, с подготовленными окружениями синтезаторов):
    python scripts/make_voices.py              # по 3 варианта на вызов
    python scripts/make_voices.py --variants 2 --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from app.services.caller_gender import FEMALE, MALE, detect, detect_in_text  # noqa: E402
from import_tickets import caller_from  # noqa: E402
from make_audio import speakable  # noqa: E402

TICKETS = BACKEND_DIR / "data" / "tickets.json"
OUT_DIR = BACKEND_DIR.parent / "frontend" / "public" / "audio"
TTS = Path.home() / ".cache" / "dds112-tts"

# Отобраны на слух заказчиком 25.09: Silero aidar и kseniya, Piper irina
# звучали неестественно и заменены улучшенными голосами macOS.
VOICES = {
    MALE: [("piper", "denis"), ("piper", "dmitri"), ("piper", "ruslan"),
           ("silero", "eugene"), ("say", "Yuri (Enhanced)")],
    FEMALE: [("silero", "baya"), ("silero", "xenia"), ("say", "Katya (Enhanced)"),
             ("say", "Milena (Enhanced)"), ("say", "Milena")],
}

SILERO_SCRIPT = """
import sys, torch, soundfile
model = torch.package.PackageImporter(sys.argv[1]).load_pickle("tts_models", "model")
model.to(torch.device("cpu"))
for line in sys.stdin:
    speaker, out, text = line.rstrip("\\n").split("\\t", 2)
    audio = model.apply_tts(text=text, speaker=speaker, sample_rate=48000)
    soundfile.write(out, audio.numpy(), 48000)
    print(out, flush=True)
"""


def gender_of(call: dict) -> str | None:
    name, _, _ = caller_from(call)
    return detect(name) if name != "Заявитель" else detect_in_text(call["situation"])


def synth_piper(voice: str, text: str, wav: Path) -> None:
    model = TTS / "voices" / f"ru_RU-{voice}-medium.onnx"
    subprocess.run(
        [str(TTS / "venv" / "bin" / "piper"), "--model", str(model), "--output_file", str(wav)],
        input=text.encode("utf-8"), check=True, capture_output=True,
    )


def synth_say(voice: str, text: str, wav: Path) -> None:
    aiff = wav.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-r", "185", "-o", str(aiff), text], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), str(wav)], check=True)
    aiff.unlink(missing_ok=True)


def to_mp3(wav: Path, target: Path, telephone: bool) -> None:
    """Моно 64 кбит/с; часть вариантов — «по телефону»: узкая полоса и лёгкий шум.

    Настоящий вызов звучит не как диктор в студии: полоса телефонной линии
    300–3400 Гц и шум улицы. Разбирать речь сквозь них — тоже навык.
    """
    chain = ["-ac", "1"]
    if telephone:
        chain = [
            "-filter_complex",
            "[0:a]highpass=f=300,lowpass=f=3400,volume=1.4[v];"
            "anoisesrc=color=pink:amplitude=0.012[n];"
            "[v][n]amix=inputs=2:duration=first:dropout_transition=0[out]",
            "-map", "[out]", "-ac", "1",
        ]
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), *chain, "-b:a", "64k", str(target)],
        check=True,
    )


def main(variants: int, force: bool, only: str | None) -> None:
    if not shutil.which("ffmpeg"):
        raise SystemExit("Нужен ffmpeg.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.loads(TICKETS.read_text(encoding="utf-8"))
    silero_jobs: list[tuple[str, Path, str, Path, bool]] = []
    plan: list[tuple[Path, str, str, str, bool]] = []  # target, engine, voice, text, telephone

    for ticket in payload["tickets"]:
        for call in ticket["calls"]:
            key = f"ticket-{ticket['ticket']}-{call['no']}"
            if only and key != only:
                continue
            gender = gender_of(call)
            pool = VOICES[gender] if gender else VOICES[MALE] + VOICES[FEMALE]
            # Зерно — от ключа вызова: пересборка даёт те же голоса, и файлы
            # в репозитории не меняются без причины.
            rng = random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:8], 16))
            chosen = rng.sample(pool, k=min(variants, len(pool)))
            text = speakable(f"{call['situation']}. Адрес: {call['address']}")
            for index, (engine, voice) in enumerate(chosen, start=1):
                target = OUT_DIR / f"{key}-v{index}.mp3"
                if target.exists() and not force:
                    continue
                # Каждый третий вариант — «по телефону».
                plan.append((target, engine, voice, text, index == 3))

    tmp = Path(tempfile.mkdtemp(prefix="voices-"))
    try:
        for target, engine, voice, text, phone in plan:
            wav = tmp / (target.stem + ".wav")
            if engine == "silero":
                silero_jobs.append((voice, wav, text, target, phone))
                continue
            (synth_piper if engine == "piper" else synth_say)(voice, text, wav)
            to_mp3(wav, target, phone)
            print(f"  {target.name}  {engine}/{voice}{' · телефон' if phone else ''}")

        if silero_jobs:
            # Silero — одним процессом: загрузка модели дороже самого синтеза.
            proc = subprocess.run(
                [str(TTS / "silero-venv" / "bin" / "python"), "-c", SILERO_SCRIPT, str(TTS / "silero" / "v4_ru.pt")],
                input="".join(f"{v}\t{w}\t{t}\n" for v, w, t, _, _ in silero_jobs).encode("utf-8"),
                check=True, capture_output=True,
            )
            for voice, wav, _, target, phone in silero_jobs:
                to_mp3(wav, target, phone)
                print(f"  {target.name}  silero/{voice}{' · телефон' if phone else ''}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = sum(f.stat().st_size for f in OUT_DIR.glob("*-v*.mp3"))
    print(f"\nозвучено {len(plan)}, всего вариантов {len(list(OUT_DIR.glob('*-v*.mp3')))}, {total // 1024} КБ")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Озвучивание вызовов голосами по полу заявителя")
    cli.add_argument("--variants", type=int, default=3)
    cli.add_argument("--force", action="store_true")
    cli.add_argument("--only", help="один вызов для пробы, например ticket-1-1")
    args = cli.parse_args()
    main(args.variants, args.force, args.only)
