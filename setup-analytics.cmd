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

echo ▶ Préparation de l'analytics (dossiers & fichiers)...
"%PY%" tools\setup_analytics.py
echo.
echo (Terminé) Appuie sur une touche pour fermer...
pause >nul
