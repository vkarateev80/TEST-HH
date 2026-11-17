#!/bin/bash
# Сборка приложения для macOS.
#
#   ./macos/build.sh            собрать dist/Проверка договоров.app
#   ./macos/build.sh --check    собрать и проверить: открыть окно, загрузить учебные файлы, прочитать таблицу
#
# Нужны Xcode Command Line Tools (xcode-select --install): в них есть и компилятор Swift, и Python 3.
set -euo pipefail
cd "$(dirname "$0")/.."

APP="dist/Проверка договоров.app"
PROGRAM="$APP/Contents/Resources/app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$PROGRAM"

# 1. Оболочка: окно и запуск программы. Собирается для обоих видов процессоров Mac
#    (Apple Silicon и Intel) и склеивается в один файл.
mkdir -p build
for arch in arm64 x86_64; do
    swiftc -O -swift-version 5 -target "$arch-apple-macos11.0" \
        -o "build/ContractCheck-$arch" macos/main.swift
done
lipo -create build/ContractCheck-arm64 build/ContractCheck-x86_64 \
    -output "$APP/Contents/MacOS/ContractCheck"
cp macos/Info.plist "$APP/Contents/Info.plist"

# 2. Сама программа — те же файлы, что запускаются командой python3 app.py
cp app.py "$PROGRAM/"
cp -R contractcheck static documents "$PROGRAM/"
find "$APP" -name "__pycache__" -type d -prune -exec rm -rf {} +

# 3. Локальная подпись, чтобы macOS запускала приложение на этом компьютере
codesign --force --sign - "$APP" >/dev/null 2>&1

echo "Готово: $APP"
if [ "${1:-}" = "--check" ]; then
    "$APP/Contents/MacOS/ContractCheck" --selftest
fi
