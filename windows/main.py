"""Приложение для Windows: собственное окно, в котором открыт тот же интерфейс.

Делает то же, что оболочка для macOS (macos/main.swift):
  1) запускает сервер программы на свободном порту своего компьютера (127.0.0.1);
  2) показывает его страницу в окне;
  3) завершает работу, когда окно закрыто.

Окно создаёт библиотека pywebview; внутри него Microsoft Edge WebView2, который
есть в Windows 10 и 11. Сборка в один файл ContractCheck.exe: windows\\build.bat.
Python в этот файл уже вложен, на компьютере пользователя он не нужен.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # app.py лежит на уровень выше

import webview   # noqa: E402  (pip install pywebview)

import app       # noqa: E402

TITLE = "Проверка условий договоров поставки"
SELFTEST = "--selftest" in sys.argv        # самопроверка сборки: ContractCheck.exe --selftest
REPORT = Path("selftest.txt")              # у оконного приложения нет консоли, итог пишем в файл
result = {"ok": False}


def selftest(window) -> None:
    """Загрузить учебные файлы и прочитать номера договоров из таблицы."""
    window.evaluate_js("document.getElementById('samplesBtn').click()")
    time.sleep(3)
    rows = window.evaluate_js(
        "Array.from(document.querySelectorAll('#table tbody tr .num'))"
        ".map(function (n) { return n.textContent; }).join(', ')")
    result["ok"] = bool(rows)
    REPORT.write_text(f"SELFTEST OK: окно открыто, в таблице договоры: {rows}" if rows
                      else "SELFTEST FAIL: таблица не построена", encoding="utf-8")
    window.destroy()


def selftest_timeout() -> None:
    REPORT.write_text("SELFTEST FAIL: самопроверка не завершилась за 90 секунд", encoding="utf-8")
    os._exit(1)


def main() -> None:
    server = app.make_server(0)                       # 0 — любой свободный порт
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"

    window = webview.create_window(TITLE, url, width=1400, height=900, min_size=(720, 520))
    if SELFTEST:
        window.events.loaded += lambda: selftest(window)
        timer = threading.Timer(90, selftest_timeout)
        timer.daemon = True
        timer.start()
    # В Windows требуем современный движок (WebView2), а не устаревший Internet Explorer.
    webview.start(gui="edgechromium" if sys.platform == "win32" else None)

    server.shutdown()
    if SELFTEST and not result["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
