"""Общие заготовки для тестов: учебные файлы и шаблоны документов того же формата."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contractcheck import analyze  # noqa: E402

CHECK_DATE = date(2026, 3, 10)


def sample_files():
    return [{"name": p.name, "text": p.read_text(encoding="utf-8")}
            for p in sorted((ROOT / "documents").glob("*.txt"))]


def run(files, check=CHECK_DATE, before=None):
    return analyze(files, check, before)


def row(report, number):
    matches = [r for r in report["contracts"] if r["number"] == number]
    assert len(matches) == 1, f"ожидался один договор {number}, найдено {len(matches)}"
    return matches[0]


def contract(number="STN-200", supplier="ООО «Новый Поставщик»",
             amount="2.1. Общая стоимость поставки составляет 500 000 (пятьсот тысяч) рублей, включая НДС.",
             delivery="3.1. Поставщик обязуется поставить товар не позднее 01.06.2026.",
             status="подписан обеими сторонами 01.02.2026.", extra=""):
    return {"name": f"contract_{number}.txt", "text": "\n".join([
        f"ДОГОВОР ПОСТАВКИ № {number}",
        "Дата: 01.02.2026",
        f"Статус: {status}",
        "",
        f"1.1. Покупатель: ООО «СеверМет». Поставщик: {supplier}.",
        "1.2. Предмет: поставка товара.",
        "",
        amount,
        delivery,
        extra,
        "",
        "5.1. Изменения условий действуют после подписания дополнительного соглашения обеими сторонами "
        "и наступления указанной в нем даты вступления в силу.",
    ])}


def amendment(number="STN-200", n=1, supplier="ООО «Новый Поставщик»",
              status="подписано обеими сторонами 01.03.2026.",
              body="1. Пункт 3.1 договора изложить в следующей редакции: "
                   "«Поставщик обязуется поставить товар не позднее 15.06.2026».",
              effective="4. Настоящее соглашение вступает в силу 01.03.2026.", name=None):
    return {"name": name or f"amendment_{number}_{n}.txt", "text": "\n".join([
        f"ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № {n} К ДОГОВОРУ {number}",
        "Дата: 01.03.2026",
        f"Статус: {status}",
        f"Покупатель: ООО «СеверМет». Поставщик: {supplier}.",
        "",
        body,
        "",
        effective,
    ])}
