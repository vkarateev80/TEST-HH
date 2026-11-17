#!/usr/bin/env python3
"""Локальный сервер прототипа.

Запуск:  python3 app.py            → http://127.0.0.1:8000
         python3 app.py --port 9000

Сервер ничего не хранит: каждый запрос /api/analyze получает тексты файлов
и дату проверки и возвращает готовый отчёт.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from contractcheck import analyze

ROOT = Path(__file__).resolve().parent
SAMPLES_DIR = ROOT / "documents"
MAX_BODY = 5 * 1024 * 1024      # защита от случайно выбранного огромного файла

STATIC = {
    "/": ("static/index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("static/app.js", "text/javascript; charset=utf-8"),
    "/static/style.css": ("static/style.css", "text/css; charset=utf-8"),
}


def read_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1251")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in STATIC:
            file_name, content_type = STATIC[path]
            self._send(200, (ROOT / file_name).read_bytes(), content_type)
        elif path == "/api/samples":
            # Учебные файлы из папки documents — чтобы не выбирать их вручную при показе.
            files = [{"name": p.name, "text": read_text(p)} for p in sorted(SAMPLES_DIR.glob("*.txt"))]
            self._json(200, {"files": files})
        else:
            self._json(404, {"error": "Не найдено"})

    def do_POST(self) -> None:
        if self.path != "/api/analyze":
            self._json(404, {"error": "Не найдено"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._json(413, {"error": "Слишком большой объём файлов"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            check_date = date.fromisoformat(payload["check_date"])
            before = date.fromisoformat(payload["before_date"]) if payload.get("before_date") else None
            files = [{"name": str(f["name"]), "text": str(f["text"])} for f in payload["files"]]
        except (ValueError, KeyError, TypeError):
            self._json(400, {"error": "Некорректный запрос: нужны check_date (ГГГГ-ММ-ДД) и files"})
            return
        self._json(200, analyze(files, check_date, before))

    def log_message(self, fmt: str, *args) -> None:   # не засоряем консоль строкой на каждый запрос
        pass


def make_server(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def _exit_when_parent_closes() -> None:
    """Для приложения-оболочки: оно держит открытым наш стандартный ввод.
    Когда оболочка закрывается (даже аварийно), ввод обрывается — и сервер завершается сам."""
    sys.stdin.read()
    os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка условий договоров поставки")
    parser.add_argument("--port", type=int, default=8000, help="0 — выбрать любой свободный порт")
    parser.add_argument("--exit-with-parent", action="store_true",
                        help="завершиться, когда закроется запустившая программа (нужно приложению для macOS)")
    args = parser.parse_args()
    # В Windows при перенаправлении вывода русские буквы могут не поместиться в кодировку консоли.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    server = make_server(args.port)
    if args.exit_with_parent:
        threading.Thread(target=_exit_when_parent_closes, daemon=True).start()
    port = server.server_address[1]
    print(f"Откройте в браузере: http://127.0.0.1:{port}  (остановить — Ctrl+C)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено")


if __name__ == "__main__":
    main()
