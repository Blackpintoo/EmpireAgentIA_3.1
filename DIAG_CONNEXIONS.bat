@echo off
setlocal
title Diagnostic connexions
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe tools\diag_connexions.py
) else (
    python tools\diag_connexions.py
)

echo.
pause
