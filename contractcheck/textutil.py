"""Базовые операции с текстом: абзацы, даты, суммы, границы предложений."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

# Точки внутри чисел и дат («15.04.2026», «пункт 3.1», «0.1%») мешают искать конец
# предложения. В рабочей копии текста заменяем их на похожий символ. Длина строки
# не меняется, поэтому позиции в рабочей копии и в исходном тексте совпадают,
# а цитата всегда вырезается из исходного текста.
DOT = "\u2024"

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

# Шаблоны для рабочей (замаскированной) копии текста.
DATE = rf"(?:\d{{1,2}}{DOT}\d{{1,2}}{DOT}\d{{4}}|\d{{1,2}}\s+(?:{'|'.join(MONTHS)})\s+\d{{4}})"
AMOUNT = rf"(?:\d{{1,3}}(?:[ \u00a0\u202f]\d{{3}})+|\d+)(?:[,{DOT}]\d{{1,2}})?"
PERCENT = rf"\d+(?:[,{DOT}]\d+)?"


@dataclass
class Paragraph:
    n: int      # номер абзаца в документе, начиная с 1
    text: str   # текст абзаца как в исходном файле


def split_paragraphs(text: str) -> List[Paragraph]:
    """Абзац — это непустая строка файла. Номера идут подряд с 1."""
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: List[Paragraph] = []
    for line in text.split("\n"):
        line = line.strip()
        if line:
            paragraphs.append(Paragraph(len(paragraphs) + 1, line))
    return paragraphs


def mask(text: str) -> str:
    """Рабочая копия текста: точки между цифрами заменены на DOT."""
    return re.sub(r"(?<=\d)\.(?=\d)", DOT, text)


def sentence_bounds(masked: str, start: int, end: int) -> Tuple[int, int]:
    """Границы предложения, в которое попадает фрагмент [start, end)."""
    left = 0
    for m in re.finditer(r"[.;!?]\s+", masked[:start]):
        left = m.end()
    m = re.search(r"[.;!?](?=\s|$)", masked[end:])
    right = end + m.start() if m else len(masked)
    return left, right


def cut_quote(text: str, left: int, right: int) -> str:
    """Точная цитата из исходного текста. Если кавычка «…» открыта, но не закрыта,
    цитата продлевается до закрывающей кавычки."""
    quote = text[left:right]
    if quote.count("«") > quote.count("»"):
        closing = text.find("»", right)
        if closing != -1:
            quote = text[left:closing + 1]
    return quote.strip()


def parse_date(raw: str) -> Optional[date]:
    """«15.04.2026» или «15 апреля 2026» → дата. Несуществующая дата → None."""
    raw = raw.replace(DOT, ".").strip().lower()
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", raw)
    if m:
        day, month, year = (int(x) for x in m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", raw)
        if not m or m.group(2) not in MONTHS:
            return None
        day, month, year = int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def format_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def parse_amount(raw: str) -> Optional[Decimal]:
    """«1 380 000» или «1 380 000,50» → число рублей."""
    cleaned = re.sub(r"[ \u00a0\u202f]", "", raw).replace(DOT, ".").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def format_amount(value: Decimal) -> str:
    whole = int(value)
    text = f"{whole:,}".replace(",", "\u00a0")
    if value != whole:
        text += "," + f"{value - whole:.2f}"[2:]
    return text + "\u00a0₽"


def parse_percent(raw: str) -> Optional[Decimal]:
    """«0,1» → 0.1 (проценты)."""
    try:
        return Decimal(raw.replace(DOT, ".").replace(",", "."))
    except InvalidOperation:
        return None


def format_percent(value: Decimal) -> str:
    return f"{value.normalize():f}".replace(".", ",") + "%"
