"""Цитаты из речи заявителя к замечаниям разбора.

Замечание «следовало записать дом 21» само по себе спорно: обучающийся вправе
спросить, откуда это известно. Ответ — фрагмент расшифровки, где заявитель
это сказал. Цитата всегда дословная, из текста вызова, и никогда не
сочиняется: если фрагмент не нашёлся, замечание остаётся без цитаты.
Идея взята из практики команды: эталон без подтверждающей цитаты
не принимается.
"""

from __future__ import annotations

import re

RADIUS = 45


def excerpt(text: str, start: int, end: int, radius: int = RADIUS) -> str:
    """Фрагмент вокруг найденного места, обрезанный по границам слов."""
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    if left > 0:
        cut = text.rfind(" ", left, start)
        if cut != -1:
            left = cut + 1
    if right < len(text):
        cut = text.find(" ", end, right)
        if cut != -1:
            right = cut
    piece = text[left:right].strip(" ,;")
    return ("…" if left > 0 else "") + piece + ("…" if right < len(text) else "")


def find(text: str, needle: str) -> str | None:
    """Цитата с названным значением: без учёта регистра и «ё»."""
    if not text or not needle or not needle.strip():
        return None
    haystack = text.lower().replace("ё", "е")
    target = needle.strip().lower().replace("ё", "е")
    at = haystack.find(target)
    if at == -1:
        return None
    return excerpt(text, at, at + len(target))


def find_digits(text: str, digits: str) -> str | None:
    """Цитата с номером телефона: цифры в речи разделены как угодно."""
    if not text or not digits:
        return None
    wanted = "".join(ch for ch in digits if ch.isdigit())
    if len(wanted) < 5:
        return None
    # Позиция каждой цифры в тексте — чтобы найти последовательность цифр
    # независимо от пробелов, дефисов и скобок между ними.
    positions = [i for i, ch in enumerate(text) if ch.isdigit()]
    stream = "".join(text[i] for i in positions)
    at = stream.find(wanted)
    if at == -1 and len(wanted) == 10:
        at = stream.find(wanted[-7:])
        if at != -1:
            at -= 3 if at >= 3 else 0
    if at == -1:
        return None
    start = positions[at]
    end = positions[min(at + len(wanted), len(positions)) - 1] + 1
    return excerpt(text, start, end)


def find_any(text: str, pattern: re.Pattern[str]) -> str | None:
    """Цитата по регулярному выражению — для признаков опросной карты."""
    if not text:
        return None
    found = pattern.search(text)
    return excerpt(text, found.start(), found.end()) if found else None
