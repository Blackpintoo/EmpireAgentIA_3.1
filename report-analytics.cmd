@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
chcp 65001 >nul 2>nul

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
where "%PY%" >nul 2>nul
if errorlevel 1 set "PY=python"

set "PYTHONUTF8=1"
set "PYTHONPATH=%CD%"

echo ▶ Génération du rapport analytique...
"%PY%" tools\report_kpis.py
echo.
echo Ouvre maintenant: reports\index.html
echo.
pause
