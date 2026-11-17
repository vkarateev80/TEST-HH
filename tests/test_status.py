"""Статус документа: что меняет условия договора, а что только показывается для проверки."""
import unittest
from datetime import date

from helpers import amendment, contract, row, run

BASE = "2026-06-01"       # срок поставки в шаблоне договора
CHANGED = "2026-06-15"    # срок поставки в шаблоне допсоглашения


def delivery(files, check=date(2026, 3, 10)):
    return row(run(files, check), "STN-200")["delivery_date"]


class DocumentStatus(unittest.TestCase):
    def test_signed_amendment_in_force_changes_the_term(self):
        fld = delivery([contract(), amendment()])
        self.assertEqual((fld["status"], fld["value"]), ("ok", CHANGED))
        self.assertEqual(fld["changed_by"]["doc_name"], "amendment_STN-200_1.txt")

    def test_unsigned_amendment_is_only_a_proposal(self):
        fld = delivery([contract(), amendment(status="проект на согласовании, не подписан ни одной стороной.")])
        self.assertEqual((fld["status"], fld["value"]), ("ok", BASE))
        self.assertEqual((fld["pending"][0]["role"], fld["pending"][0]["value"]), ("proposal", CHANGED))

    def test_amendment_signed_by_one_party_is_not_applied(self):
        fld = delivery([contract(), amendment(status="подписано поставщиком 01.03.2026.")])
        self.assertEqual(fld["value"], BASE)
        self.assertEqual(fld["pending"][0]["role"], "proposal")

    def test_amendment_with_future_effective_date_is_not_in_force_yet(self):
        fld = delivery([contract(), amendment(effective="4. Настоящее соглашение вступает в силу 01.04.2026.")])
        self.assertEqual((fld["status"], fld["value"]), ("ok", BASE))
        self.assertEqual(fld["pending"][0]["role"], "not_in_force")

    def test_same_amendment_applies_once_check_date_reaches_effective_date(self):
        files = [contract(), amendment(effective="4. Настоящее соглашение вступает в силу 01.04.2026.")]
        self.assertEqual(delivery(files, date(2026, 4, 1))["value"], CHANGED)

    def test_signed_amendment_without_effective_date_requires_review(self):
        fld = delivery([contract(), amendment(effective="")])
        self.assertEqual((fld["status"], fld["value"]), ("review", BASE))
        self.assertIn("дата вступления в силу не найдена", " ".join(fld["notes"]))

    def test_effective_from_signing_date_is_understood(self):
        fld = delivery([contract(), amendment(effective="4. Настоящее соглашение вступает в силу с даты подписания.")])
        self.assertEqual((fld["status"], fld["value"]), ("ok", CHANGED))

    def test_later_amendment_wins_regardless_of_upload_order(self):
        second = amendment(
            n=2, status="подписано обеими сторонами 05.03.2026.",
            body="1. Пункт 3.1 договора изложить в следующей редакции: "
                 "«Поставщик обязуется поставить товар не позднее 30.06.2026».",
            effective="4. Настоящее соглашение вступает в силу 05.03.2026.")
        for files in ([contract(), amendment(), second], [second, amendment(), contract()]):
            fld = delivery(files)
            self.assertEqual(fld["value"], "2026-06-30")
            self.assertEqual(fld["changed_by"]["title"], "Дополнительное соглашение № 2")
            self.assertEqual(fld["original"]["display"], "01.06.2026")

    def test_letter_never_changes_terms_even_with_firm_wording(self):
        letter = {"name": "letter.txt", "text": "\n".join([
            "ПИСЬМО ПОСТАВЩИКА",
            "Статус: подписано обеими сторонами 01.03.2026.",
            "Тема: договор STN-200",
            "Сообщаем: срок поставки — не позднее 20.07.2026.",
        ])}
        fld = delivery([contract(), letter])
        self.assertEqual((fld["status"], fld["value"]), ("ok", BASE))
        self.assertEqual((fld["pending"][0]["role"], fld["pending"][0]["value"]), ("proposal", "2026-07-20"))

    def test_amendment_with_other_supplier_requires_review(self):
        fld = delivery([contract(), amendment(supplier="ООО «Другая Компания»")])
        self.assertEqual((fld["status"], fld["value"]), ("review", BASE))

    def test_relative_change_is_not_taken_as_new_amount(self):
        files = [contract(), amendment(body="1. Увеличить общую стоимость поставки на 70 000 рублей.")]
        fld = row(run(files), "STN-200")["amount"]
        self.assertEqual((fld["status"], fld["value"]), ("review", 500000))

    def test_signed_amendment_changes_the_penalty_rate(self):
        base = contract(extra="4.1. Неустойка за просрочку поставки составляет 0,1% стоимости "
                              "просроченной части поставки за каждый день.")
        change = amendment(body="1. Пункт 4.1 договора изложить в следующей редакции: «Неустойка за просрочку "
                                "поставки составляет 0,2% стоимости просроченной части поставки за каждый день».")
        fld = row(run([base, change]), "STN-200")["penalty_rate"]
        self.assertEqual((fld["status"], fld["value"]), ("ok", 0.2))
        self.assertEqual(fld["original"]["display"], "0,1% за каждый день")
        # то же допсоглашение, но не подписанное, ставку не меняет
        draft = amendment(status="не подписано.", body=change["text"].split("\n")[5])
        fld = row(run([base, draft]), "STN-200")["penalty_rate"]
        self.assertEqual((fld["value"], fld["pending"][0]["role"], fld["pending"][0]["value"]), (0.1, "proposal", 0.2))

    def test_relative_change_of_penalty_requires_review(self):
        base = contract(extra="4.1. Неустойка за просрочку поставки составляет 0,1% стоимости "
                              "просроченной части поставки за каждый день.")
        fld = row(run([base, amendment(body="1. Увеличить размер неустойки на 0,1%.")]), "STN-200")["penalty_rate"]
        self.assertEqual((fld["status"], fld["value"]), ("review", 0.1))

    def test_amendment_to_missing_contract_is_listed_for_review(self):
        report = run([contract(), amendment(number="STN-999")])
        self.assertEqual(row(report, "STN-200")["delivery_date"]["value"], BASE)
        self.assertEqual(len(report["unlinked"]), 1)
        self.assertIn("STN-999 не загружен", report["unlinked"][0]["reason"])

    def test_unknown_document_type_is_listed_for_review(self):
        report = run([contract(), {"name": "note.txt", "text": "Заметка по договору STN-200: позвонить поставщику."}])
        self.assertEqual(report["unlinked"][0]["reason"], "Тип документа не определён")


if __name__ == "__main__":
    unittest.main()
