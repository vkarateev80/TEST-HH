"""Правила извлечения полей из текста.

Каждое поле описано одним объектом FieldRule. Чтобы добавить новое поле
(например, ставку неустойки), нужно описать ещё одно правило и добавить его
в список FIELD_RULES — остальной код (сведение условий, отчёт) работает с любым правилом.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Pattern, Tuple

from .textutil import (AMOUNT, DATE, PERCENT, Paragraph, cut_quote, format_amount, format_date,
                       format_percent, mask, parse_amount, parse_date, parse_percent, sentence_bounds)


@dataclass
class Found:
    """Значение, найденное в тексте, вместе с адресом: абзац и точная цитата."""
    value: Any          # число рублей, дата или строка; None — если значение не разобрано
    display: str        # как показать пользователю
    paragraph: int      # номер абзаца в документе
    quote: str          # точная цитата из исходного текста
    uncertain: bool = False   # значение найдено, но доверять ему нельзя


@dataclass(frozen=True)
class FieldRule:
    key: str                           # имя поля в отчёте
    label: str                         # название для пользователя
    topic: Pattern                     # слова, по которым понятно, что абзац говорит об этом поле
    statements: Tuple[Pattern, ...]    # формулировки, задающие условие целиком: «стоимость составляет N рублей»
    changes: Tuple[Pattern, ...]       # формулировки изменения: «изменить … на N» (не для договоров)
    blockers: Optional[Pattern]        # если такое слово стоит в предложении перед формулировкой — она о другом
    relative: Optional[Pattern]        # «увеличить на N» — это прибавка, а не новое значение
    parse: Callable[[str], Any]
    show: Callable[[Any], str]
    detail: Optional[Pattern] = None   # уточнение из того же предложения, дословно добавляется к значению


def _rx(pattern: str) -> Pattern:
    return re.compile(pattern, re.IGNORECASE)


_MONEY = rf"(?P<value>{AMOUNT})\s*(?:\([^)]*\)\s*)?руб"
_DEADLINE = rf"(?:(?<![а-яё])(?:не\s+позднее|до|по)\s+|[:—–-]\s*)(?P<value>{DATE})"

AMOUNT_RULE = FieldRule(
    key="amount",
    label="Сумма договора",
    topic=_rx(r"стоимост|цен[аыу]\s+договора"),
    # «Общая стоимость поставки составляет 1 200 000 (…) рублей»
    statements=(_rx(rf"(?:стоимость|цена)(?:\s+[а-яё]+){{0,4}}?\s+составляет\s+{_MONEY}"),),
    # «изменить общую стоимость поставки на 1 450 000 рублей»
    changes=(_rx(rf"(?:стоимост[а-яё]*|цен[а-яё]*\s+договора)[^.;]{{0,60}}?\s(?P<prep>на|до)\s+{_MONEY}"),),
    # аванс, лимит бюджета и предварительные оценки — не сумма договора
    blockers=_rx(r"лимит|бюджет|аванс|предоплат|ориентировочн|предварительн"),
    relative=_rx(r"увелич|уменьш|сниз|повыс"),
    parse=parse_amount,
    show=format_amount,
)

DELIVERY_RULE = FieldRule(
    key="delivery_date",
    label="Срок поставки",
    topic=_rx(r"срок[а-яё]*\s+поставки|постав(?:ить|ит)(?![а-яё])|поставка\s+(?:осуществляется|производится)"),
    # «Поставщик обязуется поставить оборудование не позднее 15.04.2026»
    statements=(_rx(
        r"(?:постав(?:ить|ит|ляет|ляется|ляются)|срок[а-яё]*\s+поставки"
        r"|поставка\s+(?:осуществляется|производится|выполняется))"
        rf"[^.;]{{0,80}}?{_DEADLINE}"),),
    # «перенести срок поставки с 20.03.2026 на 27.03.2026»
    changes=(_rx(rf"(?:срок[а-яё]*\s+поставки|поставк[уи])[^.;]{{0,60}}?\sна\s+(?P<value>{DATE})"),),
    # срок оплаты и дата приёмки — не срок поставки
    blockers=_rx(r"оплат|плат[её]ж|при[её]мк"),
    relative=None,
    parse=parse_date,
    show=format_date,
)

# Между словом «неустойка» и ставкой не должно быть слов об оплате:
# неустойка за просрочку оплаты — это ответственность покупателя, другое условие.
_PENALTY_GAP = r"(?:(?!оплат|плат[её]ж)[^.;%])"

PENALTY_RULE = FieldRule(
    key="penalty_rate",
    label="Ставка неустойки",
    topic=_rx(r"неустойк"),
    # «Неустойка за просрочку поставки составляет 0,1% стоимости … за каждый день, но не более 10% …»
    # Берётся первый процент после слова «неустойка»; предел «не более 10%» остаётся в цитате.
    statements=(_rx(
        rf"неустойк[аиу]{_PENALTY_GAP}{{0,80}}?(?:составляет|в\s+размере|[:—–])\s*(?P<value>{PERCENT})\s*%"),),
    # «изменить размер неустойки на 0,2%»
    changes=(_rx(rf"неустойк[аиу]{_PENALTY_GAP}{{0,60}}?\s(?P<prep>на|до)\s+(?P<value>{PERCENT})\s*%"),),
    blockers=None,
    relative=_rx(r"увелич|уменьш|сниз|повыс"),
    parse=parse_percent,
    show=format_percent,
    detail=_rx(r"за\s+кажд[а-яё]+\s+[а-яё]+"),     # «за каждый день»
)

FIELD_RULES: Tuple[FieldRule, ...] = (AMOUNT_RULE, DELIVERY_RULE, PENALTY_RULE)

_UNCHANGED = _rx(r"без\s+изменени|не\s+изменя")


def find_values(rule: FieldRule, paragraphs: List[Paragraph], with_changes: bool) -> List[Found]:
    """Все значения поля, найденные в документе. with_changes=True разрешает
    формулировки «изменить на …» — их ищем в допсоглашениях, проектах и письмах."""
    patterns = list(rule.statements) + (list(rule.changes) if with_changes else [])
    found: List[Found] = []
    seen = set()
    for par in paragraphs:
        masked = mask(par.text)
        for pattern in patterns:
            for m in pattern.finditer(masked):
                span = (par.n, m.start("value"), m.end("value"))
                if span in seen:
                    continue
                left, right = sentence_bounds(masked, m.start(), m.end())
                if rule.blockers and rule.blockers.search(masked[left:m.start()]):
                    continue
                seen.add(span)
                raw = par.text[m.start("value"):m.end("value")]
                value = rule.parse(raw)
                uncertain = value is None
                if (rule.relative and m.groupdict().get("prep") == "на"
                        and rule.relative.search(masked[left:m.start("value")])):
                    uncertain = True
                display = rule.show(value) if value is not None else raw
                if rule.detail:
                    extra = rule.detail.search(masked, m.end("value"), right)
                    if extra:
                        display += " " + par.text[extra.start():extra.end()]
                found.append(Found(
                    value=value,
                    display=display,
                    paragraph=par.n,
                    quote=cut_quote(par.text, left, right),
                    uncertain=uncertain,
                ))
    return found


def find_mention(rule: FieldRule, paragraphs: List[Paragraph]) -> Optional[Found]:
    """Первое предложение, где поле упомянуто. Нужно, чтобы «нет данных» тоже
    опиралось на цитату: видно, что документ говорит о поле, но значения не даёт."""
    for par in paragraphs:
        masked = mask(par.text)
        for m in rule.topic.finditer(masked):
            left, right = sentence_bounds(masked, m.start(), m.end())
            if _UNCHANGED.search(masked[left:right]):
                continue
            return Found(value=None, display="", paragraph=par.n, quote=cut_quote(par.text, left, right))
    return None
