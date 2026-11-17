"""Шесть учебных документов: таблица, четыре вопроса из задания, проверяемость источников."""
import unittest
from datetime import date

from helpers import CHECK_DATE, row, run, sample_files


class SampleDocuments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run(sample_files(), CHECK_DATE, before=date(2026, 4, 1))

    def test_table_has_three_contracts_with_suppliers(self):
        table = [(r["number"], r["supplier"]["value"]) for r in self.report["contracts"]]
        self.assertEqual(table, [
            ("STN-101", "ООО «Вектор Прибор»"),
            ("STN-102", "ООО «Контур Электро»"),
            ("STN-103", "ООО «ПромСнаб Сервис»"),
        ])
        self.assertEqual(self.report["unlinked"], [])

    def test_q1_delivery_date_of_stn101_comes_from_signed_amendment(self):
        fld = row(self.report, "STN-101")["delivery_date"]
        self.assertEqual((fld["status"], fld["value"]), ("ok", "2026-04-30"))
        self.assertEqual(fld["source"]["doc_name"], "02_amendment_signed.txt")
        self.assertIn("не позднее 30.04.2026", fld["source"]["quote"])
        self.assertEqual(fld["changed_by"]["title"], "Дополнительное соглашение № 1")
        self.assertEqual(fld["original"]["display"], "15.04.2026")
        self.assertEqual(fld["original"]["source"]["doc_name"], "01_contract.txt")

    def test_q2_amount_of_stn102_is_total_not_advance(self):
        fld = row(self.report, "STN-102")["amount"]
        self.assertEqual((fld["status"], fld["value"]), ("ok", 840000))
        self.assertEqual(fld["source"]["doc_name"], "03_contract.txt")
        self.assertIsNone(fld["changed_by"])

    def test_q3_amount_of_stn103_is_no_data_not_budget_limit(self):
        fld = row(self.report, "STN-103")["amount"]
        self.assertEqual((fld["status"], fld["value"], fld["display"]), ("no_data", None, "нет данных"))
        self.assertIn("определяется спецификацией", fld["source"]["quote"])

    def test_q4_delivery_before_april_and_unagreed_changes(self):
        answer = self.report["delivery_before"]
        ids = {r["id"]: r["number"] for r in self.report["contracts"]}
        self.assertEqual([ids[i] for i in answer["earlier"]], ["STN-102"])
        self.assertEqual(answer["unknown"], [])
        self.assertEqual([ids[i] for i in answer["other_pending"]], ["STN-101"])
        fld = row(self.report, "STN-102")["delivery_date"]
        self.assertEqual(fld["value"], "2026-03-20")           # срок поставки, а не срок оплаты 10.04.2026
        self.assertEqual(len(fld["pending"]), 1)
        proposal = fld["pending"][0]
        self.assertEqual((proposal["role"], proposal["value"]), ("proposal", "2026-03-27"))
        self.assertEqual(proposal["doc_name"], "05_supplier_email.txt")

    def test_penalty_rate_is_the_daily_rate_not_the_cap(self):
        stn101 = row(self.report, "STN-101")["penalty_rate"]
        self.assertEqual((stn101["status"], stn101["value"]), ("ok", 0.1))      # 0,1% в день, а не предел 10%
        self.assertEqual(stn101["display"], "0,1% за каждый день")
        self.assertEqual(stn101["source"]["doc_name"], "01_contract.txt")
        self.assertIn("но не более 10%", stn101["source"]["quote"])
        # допсоглашение № 1 оставляет неустойку «без изменений» — это не изменение и не повод для проверки
        self.assertIsNone(stn101["changed_by"])
        self.assertEqual(stn101["pending"], [])
        self.assertEqual(row(self.report, "STN-102")["penalty_rate"]["value"], 0.05)

    def test_penalty_rate_of_stn103_is_no_data_with_quote(self):
        fld = row(self.report, "STN-103")["penalty_rate"]
        self.assertEqual((fld["status"], fld["value"], fld["display"]), ("no_data", None, "нет данных"))
        self.assertEqual(fld["source"]["quote"], "Ставка неустойки в тексте договора не установлена")

    def test_unsigned_draft_is_shown_but_not_applied(self):
        stn101 = row(self.report, "STN-101")
        self.assertEqual(stn101["amount"]["value"], 1380000)
        self.assertEqual(stn101["amount"]["original"]["display"], "1\u00a0200\u00a0000\u00a0₽")
        proposals = {k: stn101[k]["pending"][0] for k in ("amount", "delivery_date")}
        self.assertEqual(proposals["amount"]["value"], 1450000)
        self.assertEqual(proposals["delivery_date"]["value"], "2026-05-10")
        for p in proposals.values():
            self.assertEqual((p["role"], p["doc_name"]), ("proposal", "06_amendment_draft.txt"))

    def test_every_quote_is_an_exact_fragment_of_its_paragraph(self):
        paragraphs = {(d["id"], p["n"]): p["text"] for d in self.report["documents"] for p in d["paragraphs"]}
        checked = 0
        for r in self.report["contracts"]:
            for key in (f["key"] for f in self.report["fields"]):
                fld = r[key]
                sources = [fld["source"]] + [p["source"] for p in fld["pending"]]
                if fld["original"]:
                    sources.append(fld["original"]["source"])
                for src in filter(None, sources):
                    self.assertIn(src["quote"], paragraphs[(src["doc_id"], src["paragraph"])])
                    checked += 1
        self.assertGreaterEqual(checked, 17)

    def test_file_names_and_upload_order_do_not_matter(self):
        files = sample_files()
        shuffled = [{"name": f"z{9 - i}.txt", "text": f["text"]} for i, f in enumerate(reversed(files))]
        other = run(shuffled, CHECK_DATE)
        for number in ("STN-101", "STN-102", "STN-103"):
            for key in ("amount", "delivery_date"):
                self.assertEqual(row(other, number)[key]["value"], row(self.report, number)[key]["value"])

    def test_before_effective_date_original_terms_apply(self):
        early = run(sample_files(), date(2026, 2, 28))
        stn101 = row(early, "STN-101")
        self.assertEqual(stn101["amount"]["value"], 1200000)
        self.assertEqual(stn101["delivery_date"]["value"], "2026-04-15")
        self.assertIsNone(stn101["delivery_date"]["changed_by"])
        roles = {p["doc_name"]: p["role"] for p in stn101["delivery_date"]["pending"]}
        self.assertEqual(roles["02_amendment_signed.txt"], "not_in_force")


if __name__ == "__main__":
    unittest.main()
