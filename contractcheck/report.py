"""Сведение условий: какие документы относятся к договору, какие из них меняют
условия на дату проверки, и что в итоге показать пользователю.

Главное правило: условия меняет только допсоглашение, подписанное обеими
сторонами и вступившее в силу к дате проверки. Всё остальное (письма, проекты,
ещё не вступившие в силу соглашения) показывается отдельно и значения не меняет.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .document import Document, normalize_party
from .rules import FIELD_RULES, FieldRule, Found
from .textutil import format_date

NO_DATA = "нет данных"

KIND_LABELS = {"contract": "Договор", "amendment": "Допсоглашение", "letter": "Письмо", "unknown": "Не определён"}


# ---------- Шаг 1. К какому договору относится документ ----------

def find_target(doc: Document, known_numbers: List[str]) -> Tuple[Optional[str], str]:
    """Возвращает (номер договора, причина, если связать не удалось)."""
    if doc.header_refs:
        refs = doc.header_refs[:1]          # номер в заголовке главнее упоминаний в тексте
    else:
        refs = list(doc.body_refs)
        for number in known_numbers:
            if number not in refs and doc.text_contains(number):
                refs.append(number)
    if not refs:
        return None, "В документе не найден номер договора"
    if len(refs) > 1:
        return None, "В документе упомянуто несколько договоров: " + ", ".join(refs)
    if refs[0] not in known_numbers:
        return None, f"Договор {refs[0]} не загружен"
    return refs[0], ""


# ---------- Шаг 2. Меняет ли документ условия на дату проверки ----------

def assess(doc: Document, contract: Document, check_date: date) -> Tuple[str, str]:
    """Роль документа по отношению к договору:
    applied — учтён; not_in_force — подписан, но ещё не действует;
    proposal — предложение, не согласовано; review — определить не удалось."""
    if doc.kind == "letter":
        return "proposal", "предложение, договор не изменяет"
    if doc.is_draft and doc.status == "signed":
        return "review", "в заголовке указано «проект», а статус — «подписано»"
    if doc.is_draft or doc.status == "unsigned":
        return "proposal", "проект, не подписан"
    if doc.status == "partial":
        return "proposal", "подписано не обеими сторонами"
    if doc.status == "unknown":
        return "review", "статус подписания не указан"
    if doc.supplier and contract.supplier and \
            normalize_party(doc.supplier.value) != normalize_party(contract.supplier.value):
        return "review", (f"поставщик в документе ({doc.supplier.value}) не совпадает "
                          f"с поставщиком по договору ({contract.supplier.value})")
    if doc.signed_date and doc.signed_date > check_date:
        return "not_in_force", f"подписано {format_date(doc.signed_date)} — позже даты проверки"
    if doc.effective_date is None:
        return "review", "подписано, но дата вступления в силу не найдена"
    if doc.effective_date > check_date:
        return "not_in_force", f"вступает в силу {format_date(doc.effective_date)} — позже даты проверки"
    return "applied", f"подписано обеими сторонами, действует с {format_date(doc.effective_date)}"


# ---------- Шаг 3. Значение поля в одном документе ----------

@dataclass
class Pick:
    state: str                 # value | ambiguous | mention | absent
    found: Optional[Found]
    note: str = ""


def pick(doc: Document, rule: FieldRule) -> Pick:
    candidates = doc.values.get(rule.key) or []
    if not candidates:
        mention = doc.mentions.get(rule.key)
        return Pick("mention", mention) if mention else Pick("absent", None)
    if any(c.uncertain for c in candidates):
        return Pick("ambiguous", candidates[0], "значение не удалось надёжно определить")
    distinct = {c.value for c in candidates}
    if len(distinct) > 1:
        listing = ", ".join(f"{c.display} (абз. {c.paragraph})" for c in candidates)
        return Pick("ambiguous", candidates[0], f"в документе несколько разных значений: {listing}")
    return Pick("value", candidates[0])


# ---------- Шаг 4. Итоговое значение поля по договору ----------

def _json_value(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == int(value) else float(value)
    return value


def _source(doc: Document, found: Found) -> Dict[str, Any]:
    return {"doc_id": doc.id, "doc_name": doc.name, "paragraph": found.paragraph, "quote": found.quote}


def _amendment_order(doc: Document) -> Tuple:
    number = int(doc.amendment_number) if (doc.amendment_number or "").isdigit() else 0
    return (doc.effective_date, doc.signed_date or date.min, number)


def resolve_field(rule: FieldRule, contract: Document, links: List[Tuple[Document, str, str]]) -> Dict[str, Any]:
    """links — документы по договору с их ролью и пояснением (результат assess)."""
    notes: List[str] = []
    review: List[str] = []
    current: Optional[Found] = None
    source: Optional[Dict[str, Any]] = None
    original = None
    changed_by = None
    base_unclear = False       # в самом договоре значение есть, но определить его не удалось

    base = pick(contract, rule)
    if base.state == "value":
        current, source = base.found, _source(contract, base.found)
    elif base.state == "ambiguous":
        source = _source(contract, base.found)
        notes.append("В договоре " + base.note)
        base_unclear = True
    elif base.state == "mention":
        source = _source(contract, base.found)
        notes.append("Значение в тексте договора не найдено — см. цитату")
    else:
        notes.append(f"В договоре не найдено условие: {rule.label.lower()}")

    # Действующие допсоглашения применяем по порядку вступления в силу — последнее побеждает.
    applied = sorted((d for d, role, _ in links if role == "applied"), key=_amendment_order)
    previous: Optional[Document] = None
    for doc in applied:
        change = pick(doc, rule)
        if change.state == "absent":
            continue
        if change.state != "value":
            review.append(f"{doc.title} ({doc.name}) затрагивает поле, но "
                          + (change.note or "значение не распознано"))
            continue
        if previous and _amendment_order(previous) == _amendment_order(doc) \
                and current is not None and current.value != change.found.value:
            review.append(f"{previous.title} и {doc.title} действуют с одной даты и задают разные значения")
        if original is None:
            original = {"display": current.display if current else NO_DATA, "source": source}
        current, source = change.found, _source(doc, change.found)
        notes, base_unclear = [], False     # допсоглашение задало значение заново
        changed_by = {"doc_id": doc.id, "doc_name": doc.name, "title": doc.title,
                      "effective_display": format_date(doc.effective_date)}
        previous = doc

    # Всё, что не учтено, показываем рядом как сведения для проверки.
    pending = []
    for doc, role, reason in links:
        if role == "applied":
            continue
        change = pick(doc, rule)
        if change.state == "absent":
            continue
        known = change.state == "value"
        pending.append({
            "role": role, "reason": reason, "title": doc.title,
            "doc_id": doc.id, "doc_name": doc.name,
            "value": _json_value(change.found.value) if known else None,
            "display": change.found.display if known else "значение не распознано",
            "source": _source(doc, change.found),
        })
        if role == "review":
            review.append(f"{doc.title} ({doc.name}) не учтён: {reason}")

    return {
        "status": "review" if (review or base_unclear) else ("ok" if current is not None else "no_data"),
        "value": _json_value(current.value) if current else None,
        "display": current.display if current else ("не определено" if base_unclear else NO_DATA),
        "source": source,
        "changed_by": changed_by,
        "original": original,
        "pending": pending,
        "notes": notes + review,
    }


def _supplier_field(contract: Document) -> Dict[str, Any]:
    found = contract.supplier
    return {
        "status": "ok" if found else "no_data",
        "value": found.value if found else None,
        "display": found.display if found else NO_DATA,
        "source": _source(contract, found) if found else None,
        "changed_by": None, "original": None, "pending": [],
        "notes": [] if found else ["В договоре не найдена строка «Поставщик: …»"],
    }


# ---------- Шаг 5. Отчёт целиком ----------

def _contract_flags(contract: Document, same_number: int, check_date: date) -> List[str]:
    flags = []
    if not contract.contract_number:
        flags.append("Номер договора не найден в заголовке")
    if same_number > 1:
        flags.append("Загружено несколько договоров с этим номером")
    if contract.is_draft or contract.status in ("unsigned", "partial"):
        flags.append("Договор не подписан обеими сторонами")
    elif contract.status == "unknown":
        flags.append("Статус подписания договора не указан")
    elif contract.signed_date and contract.signed_date > check_date:
        flags.append(f"Договор подписан {format_date(contract.signed_date)} — позже даты проверки")
    return flags


def _status_label(doc: Document) -> str:
    if doc.status == "signed":
        return "подписан" + (f" {format_date(doc.signed_date)}" if doc.signed_date else "")
    return {"unsigned": "не подписан", "partial": "подписан не всеми"}.get(doc.status, "статус не указан")


def delivery_before(rows: List[Dict[str, Any]], before: date) -> Dict[str, Any]:
    """Вопрос «по каким договорам поставка раньше даты и есть ли несогласованные изменения срока»."""
    earlier, unknown, other_pending = [], [], []
    for row in rows:
        fld = row["delivery_date"]
        if fld["value"] is None:
            unknown.append(row["id"])
        elif fld["value"] < before.isoformat():     # даты в формате ГГГГ-ММ-ДД сравниваются как строки
            earlier.append(row["id"])
        elif fld["pending"]:
            other_pending.append(row["id"])
    return {"date": before.isoformat(), "display": format_date(before),
            "earlier": earlier, "unknown": unknown, "other_pending": other_pending}


def build_report(documents: List[Document], check_date: date, before: Optional[date] = None) -> Dict[str, Any]:
    contracts = [d for d in documents if d.kind == "contract"]
    known = [d.contract_number for d in contracts if d.contract_number]
    related: Dict[str, List[Document]] = {number: [] for number in known}
    doc_info: Dict[str, Dict[str, str]] = {}
    unlinked = []

    for doc in documents:
        if doc.kind == "contract":
            continue
        if doc.kind == "unknown":
            number, problem = None, ("Файл пуст" if not doc.paragraphs else "Тип документа не определён")
        else:
            number, problem = find_target(doc, known)
        if number:
            related[number].append(doc)
        else:
            unlinked.append({"doc_id": doc.id, "doc_name": doc.name, "title": doc.title, "reason": problem})
            doc_info[doc.id] = {"role": "review", "reason": problem, "linked_to": ""}

    rows = []
    for contract in sorted(contracts, key=lambda d: (d.contract_number or "", d.name)):
        links = [(doc,) + assess(doc, contract, check_date) for doc in related.get(contract.contract_number, [])]
        for doc, role, reason in links:
            doc_info[doc.id] = {"role": role, "reason": reason, "linked_to": contract.contract_number}
        row = {
            "id": contract.id,
            "number": contract.contract_number or NO_DATA,
            "doc_name": contract.name,
            "flags": _contract_flags(contract, known.count(contract.contract_number), check_date),
            "supplier": _supplier_field(contract),
            "related": [{"doc_id": d.id, "doc_name": d.name, "title": d.title, "role": role, "reason": reason}
                        for d, role, reason in links],
        }
        for rule in FIELD_RULES:
            row[rule.key] = resolve_field(rule, contract, links)
        rows.append(row)

    return {
        "check_date": check_date.isoformat(),
        "check_date_display": format_date(check_date),
        "fields": [{"key": "supplier", "label": "Поставщик"}] + [{"key": r.key, "label": r.label} for r in FIELD_RULES],
        "contracts": rows,
        "unlinked": unlinked,
        "delivery_before": delivery_before(rows, before) if before else None,
        "documents": [{
            "id": d.id, "name": d.name, "kind": d.kind, "kind_label": KIND_LABELS[d.kind], "title": d.title,
            "status_label": _status_label(d),
            "role": doc_info.get(d.id, {}).get("role", "contract"),
            "reason": doc_info.get(d.id, {}).get("reason", ""),
            "linked_to": doc_info.get(d.id, {}).get("linked_to", d.contract_number or ""),
            "paragraphs": [{"n": p.n, "text": p.text} for p in d.paragraphs],
        } for d in documents],
    }
