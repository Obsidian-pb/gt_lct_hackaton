"""Приветствие переносного комплекта в консоли start.cmd.

Рисуется Python, а не echo: символы | < > ^ & в cmd пришлось бы
экранировать построчно, и одна ошибка ломает весь запуск. Только ASCII —
в консоли Windows псевдографика Юникода зависит от шрифта. Цвет — через
последовательности VT; где их нет, выводится та же картинка без цвета.
"""

import os
import sys

RED, YELLOW, BLUE, DIM, RESET = "\033[91m", "\033[93m", "\033[94m", "\033[90m", "\033[0m"

NUMBER = [
    r"   __   __   ____  ",
    r"  /_ | /_ | |___ \ ",
    r"   | |  | |   __) |",
    r"   | |  | |  / __/ ",
    r"   |_|  |_| |_____|",
]

# Puffy — иглобрюх, талисман OpenBSD: тоже служит безопасности.
PUFFY = [
    r"        \ | | /       ",
    r"     .-'''''''''-.  / ",
    r"  --(  (o)        )<  ",
    r"     '-.,,,,,,,.-'  \ ",
    r"        / | | \       ",
]


def main() -> None:
    color = sys.stdout.isatty()
    if color and os.name == "nt":
        # Пустая команда включает обработку VT-последовательностей в консоли.
        os.system("")

    def paint(text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if color else text

    print()
    for number, fish in zip(NUMBER, PUFFY):
        print("  " + paint(number, RED) + "      " + paint(fish, YELLOW))
    print()
    print("  " + paint("Учебный комплекс АРМ-112", BLUE))
    print("  " + paint("подготовка операторов Службы 112 и диспетчеров ДДС", DIM))
    print()
    print("  Команда «Игры и Теория»")
    print("  " + paint("Сибирская пожарно-спасательная академия ГПС МЧС России", DIM))
    print()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — приветствие не вправе помешать запуску
        pass
