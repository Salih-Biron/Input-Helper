@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Project environment not found. Follow the setup steps in README.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" app.py
exit /b %errorlevel%
