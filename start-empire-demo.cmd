@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

REM Définir le chemin du projet
set "PROOT=%~dp0"
if "%PROOT:~-1%"=="\" set "PROOT=%PROOT:~0,-1%"
cd /d "%PROOT%"
set "PYTHONPATH=%PROOT%"
echo [INFO] PROOT="%PROOT%"

REM Détection de l'exécutable Python
set "PYEXE="
if exist "%PROOT%\.venv\Scripts\python.exe" (
    set "PYEXE=%PROOT%\.venv\Scripts\python.exe"
) else (
    for /f "delims=" %%I in ('where python 2^>nul') do (
        set "PYEXE=%%I" & goto :py_found
    )
    echo [ERREUR] Python introuvable.
    pause & exit /b 1
)
:py_found
echo [INFO] PYEXE="%PYEXE%"

REM Installation des dépendances
echo [SETUP] Installation des dépendances...
"%PYEXE%" -m pip install -r "%PROOT%\requirements.txt" --disable-pip-version-check || (
    echo [ERREUR] Échec de l'installation des dépendances. 
    pause & exit /b 1
)

REM Vérification de la version de Python
echo [CHECK] Version Python:
"%PYEXE%" -c "import sys; print(sys.version.split()[0])" || (
    echo [ERREUR] Échec de la vérification de la version Python.
    pause & exit /b 1
)

REM Vérification de l'importation du module orchestrator
echo [CHECK] Import orchestrator.orchestrator:
"%PYEXE%" -c "import sys; sys.path.insert(0, r'%PROOT%'); import orchestrator.orchestrator; print('OK import orchestrator.orchestrator')" || (
    echo [ERREUR] Échec de l'importation de orchestrator.orchestrator.
    pause & exit /b 1
)

echo.
echo ===============================================
echo   EmpireAgentIA — TEST (mode test)
echo ===============================================
set "DEFAULT_SYMBOLS=BTCUSD XAUUSD EURUSD LINKUSD BNBUSD ETHUSD"
set /p SYMBOLS=Entrez les symboles séparés par des espaces [défaut: %DEFAULT_SYMBOLS%] ^> 
if not defined SYMBOLS set "SYMBOLS=%DEFAULT_SYMBOLS%"

echo.
echo ===============================================
echo   Lancement en mode TEST
echo   Symbols: %SYMBOLS%
echo   Logs: %PROOT%\test_run.log
echo ===============================================

set "RUNLOG=%PROOT%\test_run.log"
echo [RUN] TEST: run_multi.py --symbols %SYMBOLS% --test
"%PYEXE%" "%PROOT%\run_multi.py" --symbols %SYMBOLS% --test 1>>"%RUNLOG%" 2>&1

if errorlevel 1 (
    echo. & echo [ERROR] Échec (code %ERRORLEVEL%). Voir %RUNLOG% & echo. & pause & exit /b 1
)

echo. & echo [OK] Fin du run TEST. Log: %RUNLOG% & echo.
echo Suivre le log en direct:
echo   Get-Content "%RUNLOG%" -Wait -Tail 200
echo.
pause
exit /b 0