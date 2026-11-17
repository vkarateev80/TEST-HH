@echo off
chcp 65001 >nul
rem Сборка приложения для Windows: один файл dist\ContractCheck.exe.
rem Python в него уже вложен, на компьютере пользователя он не нужен.
rem
rem Для самой сборки нужны Python 3.9+ и интернет (ставятся две библиотеки сборки).
rem Запуск:  windows\build.bat
cd /d "%~dp0.."

python -m pip install -r windows\requirements.txt || exit /b 1

rem Пути к данным заданы полностью: PyInstaller отсчитывает их от папки build.
python -m PyInstaller --noconfirm --clean --onefile --windowed --name ContractCheck ^
    --paths "%CD%" ^
    --add-data "%CD%\static;static" ^
    --add-data "%CD%\documents;documents" ^
    --distpath dist --workpath build --specpath build ^
    windows\main.py || exit /b 1

echo Готово: dist\ContractCheck.exe
