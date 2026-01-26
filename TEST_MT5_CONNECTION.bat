@echo off
REM ============================================================================
REM  TEST CONNEXION MT5 - NOUVEAU COMPTE
REM  Compte: 11535481 - VantageInternational-Demo
REM ============================================================================

cd /d "%~dp0"

echo.
echo ============================================================================
echo   TEST CONNEXION MT5 - NOUVEAU COMPTE DEMO
echo   Date: %DATE% %TIME%
echo ============================================================================
echo.

REM Trouver Python
set "PYTHON_CMD="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=venv\Scripts\python.exe"
) else (
    set "PYTHON_CMD=python"
)

echo [INFO] Utilisation de: %PYTHON_CMD%
echo.

%PYTHON_CMD% scripts/check_mt5_connection.py

echo.
echo ============================================================================
echo   FIN DU TEST
echo ============================================================================
echo.
pause
