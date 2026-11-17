"""Извлечение полей: изменённые значения, новый договор, ловушки и отсутствующие данные."""
import unittest

from helpers import contract, row, run, sample_files


class Extraction(unittest.TestCase):
    def test_changed_field_in_source_text_changes_result(self):
        files = sample_files()
        for f in files:
            f["text"] = f["text"].replace("840 000 (восемьсот сорок тысяч)", "915 500 (девятьсот пятнадцать тысяч пятьсот)")
            f["text"] = f["text"].replace("не позднее 20.03.2026", "не позднее 02.04.2026")
        stn102 = row(run(files), "STN-102")
        self.assertEqual(stn102["amount"]["value"], 915500)
        self.assertEqual(stn102["delivery_date"]["value"], "2026-04-02")

    def test_new_contract_of_same_format_becomes_a_row(self):
        report = run(sample_files() + [contract("STN-104", "ООО «Гамма Трейд»")])
        self.assertEqual(len(report["contracts"]), 4)
        new = row(report, "STN-104")
        self.assertEqual(new["supplier"]["value"], "ООО «Гамма Трейд»")
        self.assertEqual(new["amount"]["value"], 500000)
        self.assertEqual(new["delivery_date"]["value"], "2026-06-01")

    def test_advance_payment_is_not_the_contract_amount(self):
        fld = row(run([contract(amount="2.2. Авансовый платеж составляет 150 000 рублей "
                                       "и входит в общую стоимость по пункту 2.1.")]), "STN-200")["amount"]
        self.assertEqual((fld["status"], fld["value"]), ("no_data", None))

    def test_budget_limit_is_not_the_contract_amount(self):
        fld = row(run([contract(amount="2.2. Лимит закупки по внутреннему бюджету покупателя — 600 000 рублей.")]),
                  "STN-200")["amount"]
        self.assertEqual((fld["status"], fld["value"]), ("no_data", None))

    def test_payment_deadline_is_not_the_delivery_date(self):
        fld = row(run([contract(delivery="3.2. Оплата поставки производится не позднее 10.04.2026. "
                                         "Этот срок является сроком оплаты, а не поставки.")]),
                  "STN-200")["delivery_date"]
        self.assertEqual((fld["status"], fld["value"]), ("no_data", None))

    def test_missing_clause_gives_no_data_without_source(self):
        fld = row(run([contract(delivery="")]), "STN-200")["delivery_date"]
        self.assertEqual((fld["status"], fld["value"], fld["display"]), ("no_data", None, "нет данных"))
        self.assertIsNone(fld["source"])

    def test_amount_with_kopecks_and_date_in_words(self):
        r = row(run([contract(
            amount="2.1. Общая стоимость поставки составляет 1 250 300,50 рублей, включая НДС.",
            delivery="3.1. Поставщик обязуется поставить товар не позднее 5 июня 2026 года.")]), "STN-200")
        self.assertEqual(r["amount"]["value"], 1250300.5)
        self.assertEqual(r["delivery_date"]["value"], "2026-06-05")

    def test_two_different_amounts_require_review_instead_of_a_guess(self):
        fld = row(run([contract(extra="2.3. Общая стоимость поставки составляет 700 000 рублей.")]),
                  "STN-200")["amount"]
        self.assertEqual((fld["status"], fld["value"]), ("review", None))
        self.assertIn("несколько разных значений", " ".join(fld["notes"]))

    def test_impossible_date_requires_review(self):
        fld = row(run([contract(delivery="3.1. Поставщик обязуется поставить товар не позднее 31.02.2026.")]),
                  "STN-200")["delivery_date"]
        self.assertEqual((fld["status"], fld["value"]), ("review", None))

    def test_penalty_for_late_payment_is_not_the_delivery_penalty(self):
        fld = row(run([contract(extra="4.2. Неустойка за просрочку оплаты составляет 0,2% "
                                      "неоплаченной суммы за каждый день.")]), "STN-200")["penalty_rate"]
        self.assertEqual((fld["status"], fld["value"]), ("no_data", None))

    def test_penalty_rate_with_other_wording_and_period(self):
        fld = row(run([contract(extra="4.1. Поставщик уплачивает неустойку в размере 0.5% стоимости "
                                      "непоставленного товара за каждую неделю просрочки.")]),
                  "STN-200")["penalty_rate"]
        self.assertEqual((fld["status"], fld["value"], fld["display"]), ("ok", 0.5, "0,5% за каждую неделю"))

    def test_contract_without_penalty_clause_gives_no_data(self):
        fld = row(run([contract()]), "STN-200")["penalty_rate"]
        self.assertEqual((fld["status"], fld["value"]), ("no_data", None))
        self.assertIsNone(fld["source"])

    def test_unsigned_contract_is_flagged(self):
        r = row(run([contract(status="проект, не подписан.")]), "STN-200")
        self.assertIn("Договор не подписан обеими сторонами", r["flags"])


if __name__ == "__main__":
    unittest.main()
