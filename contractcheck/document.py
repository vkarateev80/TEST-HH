"""Разбор одного документа: тип, номер договора, статус подписания, стороны, условия."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from .rules import FIELD_RULES, Found, find_mention, find_values
from .textutil import DATE, Paragraph, mask, parse_date, split_paragraphs

# Ссылка на договор в тексте: «к договору STN-101», «по договору № 15».
# Без знака № номером считаем только слово из заглавных букв с цифрами.
_REF = re.compile(
    r"(?i:договор[а-яё]*)\s+(?i:поставки\s+)?"
    r"(?:№\s*(?P<a>[^\s,;]+)|(?P<b>[A-ZА-ЯЁ]+[-–/]?\d[\w\-–/]*))"
)


@dataclass
class Document:
    id: str
    name: str
    paragraphs: List[Paragraph]
    kind: str = "unknown"                 # contract | amendment | letter | unknown
    is_draft: bool = False                # в заголовке стоит слово «проект»
    title: str = "Документ неизвестного типа"
    contract_number: Optional[str] = None   # номер самого договора (только для kind == contract)
    header_refs: List[str] = field(default_factory=list)   # номера договоров из заголовка
    body_refs: List[str] = field(default_factory=list)     # номера договоров из всего текста
    amendment_number: Optional[str] = None
    status: str = "unknown"               # signed | unsigned | partial | unknown
    status_source: Optional[Found] = None
    signed_date: Optional[date] = None
    effective_date: Optional[date] = None
    supplier: Optional[Found] = None
    values: Dict[str, List[Found]] = field(default_factory=dict)        # поле → найденные значения
    mentions: Dict[str, Optional[Found]] = field(default_factory=dict)  # поле → упоминание без значения

    def text_contains(self, token: str) -> bool:
        """Есть ли в тексте номер договора как отдельное слово."""
        pattern = re.compile(rf"(?<![\w-]){re.escape(token)}(?![\w-])", re.IGNORECASE)
        return any(pattern.search(p.text) for p in self.paragraphs)


def clean_number(raw: str) -> str:
    return raw.strip(" .,;:«»\"'()").replace("–", "-").replace("—", "-").upper()


def normalize_party(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[«»\"'“”]", "", name)).strip().lower()


def _refs(text: str) -> List[str]:
    result = []
    for m in _REF.finditer(text):
        number = clean_number(m.group("a") or m.group("b"))
        if number and number not in result:
            result.append(number)
    return result


def _detect_kind(doc: Document) -> None:
    # Тип определяем по началу первой строки, а не по слову где-нибудь в ней:
    # «Заметка по договору …» — это не договор.
    header = doc.paragraphs[0].text.upper()
    doc.is_draft = header.startswith("ПРОЕКТ")
    title = re.sub(r"^ПРОЕКТ\s+", "", header)
    if re.match(r"ДОПОЛНИТЕЛЬН\w+\s+СОГЛАШЕНИ", title):
        doc.kind = "amendment"
        m = re.search(r"СОГЛАШЕНИ\w*\s+№\s*(\S+)", header)
        doc.amendment_number = clean_number(m.group(1)) if m else None
        doc.title = ("Проект дополнительного соглашения" if doc.is_draft else "Дополнительное соглашение") \
            + (f" № {doc.amendment_number}" if doc.amendment_number else "")
    elif title.startswith("ПИСЬМО") or (
            any(p.text.startswith("От:") for p in doc.paragraphs)
            and any(p.text.startswith("Кому:") for p in doc.paragraphs)):
        doc.kind = "letter"
        doc.title = "Письмо"
    elif title.startswith("ДОГОВОР"):
        doc.kind = "contract"
        m = re.search(r"№\s*(\S+)", doc.paragraphs[0].text)
        doc.contract_number = clean_number(m.group(1)) if m else None
        doc.title = ("Проект договора" if doc.is_draft else "Договор") \
            + (f" № {doc.contract_number}" if doc.contract_number else " без номера")


def _parse_status(doc: Document) -> None:
    """Статус берём из строки «Статус: …»."""
    for par in doc.paragraphs:
        m = re.match(r"Статус\s*:\s*(.+)", par.text, re.IGNORECASE)
        if not m:
            continue
        text = m.group(1).lower()
        if re.search(r"не\s+подписан", text) or "проект" in text:
            doc.status = "unsigned"
        elif re.search(r"подписан[оаы]?\s+(?:обеими\s+)?сторонами", text):
            doc.status = "signed"
            d = re.search(DATE, mask(text))
            doc.signed_date = parse_date(d.group(0)) if d else None
        elif "подписан" in text:
            doc.status = "partial"      # подписан, но не обеими сторонами
        doc.status_source = Found(value=doc.status, display="", paragraph=par.n, quote=par.text)
        return


def _parse_effective_date(doc: Document) -> None:
    """«Настоящее соглашение вступает в силу 01.03.2026» или «…с даты подписания»."""
    for par in doc.paragraphs:
        masked = mask(par.text)
        m = re.search(rf"вступает\s+в\s+силу\s+(?:с\s+)?({DATE})", masked, re.IGNORECASE)
        if m:
            doc.effective_date = parse_date(m.group(1))
            return
        if re.search(r"вступает\s+в\s+силу\s+(?:с\s+даты|с\s+момента|со\s+дня|после)\s+(?:его\s+)?подписания",
                     masked, re.IGNORECASE):
            doc.effective_date = doc.signed_date
            return


def _parse_supplier(doc: Document) -> None:
    for par in doc.paragraphs:
        m = re.search(r"Поставщик\s*:\s*((?:[^.«»]*«[^»]+»)|[^.]+)", par.text)
        if m:
            name = m.group(1).strip()
            doc.supplier = Found(value=name, display=name, paragraph=par.n, quote=m.group(0).strip())
            return


def parse_document(doc_id: str, name: str, text: str) -> Document:
    doc = Document(id=doc_id, name=name, paragraphs=split_paragraphs(text))
    if not doc.paragraphs:
        return doc
    _detect_kind(doc)
    _parse_status(doc)
    _parse_effective_date(doc)
    _parse_supplier(doc)
    if doc.kind != "contract":
        doc.header_refs = _refs(doc.paragraphs[0].text)
        doc.body_refs = _refs("\n".join(p.text for p in doc.paragraphs))
    for rule in FIELD_RULES:
        doc.values[rule.key] = find_values(rule, doc.paragraphs, with_changes=doc.kind != "contract")
        doc.mentions[rule.key] = None if doc.values[rule.key] else find_mention(rule, doc.paragraphs)
    return doc
