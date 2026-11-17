"""Сервер: страница открывается, /api/analyze возвращает отчёт, плохой запрос отклоняется."""
import json
import threading
import unittest
import urllib.error
import urllib.request

from helpers import sample_files

import app


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.make_server(0)      # 0 — любой свободный порт
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def post(self, payload):
        request = urllib.request.Request(self.base + "/api/analyze", data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_page_is_served(self):
        with urllib.request.urlopen(self.base + "/") as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])

    def test_analyze_returns_report(self):
        report = self.post({"check_date": "2026-03-10", "before_date": "2026-04-01", "files": sample_files()})
        self.assertEqual([r["number"] for r in report["contracts"]], ["STN-101", "STN-102", "STN-103"])
        self.assertEqual(report["check_date_display"], "10.03.2026")

    def test_samples_endpoint_lists_documents_folder(self):
        with urllib.request.urlopen(self.base + "/api/samples") as response:
            files = json.loads(response.read().decode("utf-8"))["files"]
        self.assertEqual(len(files), 6)

    def test_bad_request_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post({"check_date": "10 марта", "files": []})
        self.assertEqual(caught.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
