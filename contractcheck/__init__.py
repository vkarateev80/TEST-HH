"""Проверка условий договоров поставки по загруженным текстам.

Точка входа — функция analyze: принимает тексты файлов и дату проверки,
возвращает отчёт (словарь, готовый к отправке в интерфейс).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from .document import parse_document
from .report import build_report


def analyze(files: List[Dict[str, str]], check_date: date, before: Optional[date] = None) -> Dict[str, Any]:
    """files — список словарей {"name": имя файла, "text": содержимое}."""
    documents = [parse_document(f"d{i + 1}", f["name"], f["text"]) for i, f in enumerate(files)]
    return build_report(documents, check_date, before)
