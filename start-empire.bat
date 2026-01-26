@echo off

setlocal EnableExtensions EnableDelayedExpansion



rem ---------------------------------------------------------------

rem  Demarrage Empire Agent IA (mode REAL)

rem ---------------------------------------------------------------



cd /d "%~dp0"

chcp 65001 >nul



set "PY=python"

if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"

if exist "venv\Scripts\activate.bat" call "venv\Scripts\activate.bat"



set MODE=REAL

set LOG_LEVEL=INFO

set SYMBOLS=BTCUSD ETHUSD LINKUSD BNBUSD EURUSD XAUUSD



if not exist "orchestrator\orchestrator.py" (

    echo [ERREUR] orchestrator\orchestrator.py introuvable.

    pause

    goto :EOF

)



if not exist "config\presets\overrides.real.yaml" (

    echo [INFO] creation config\presets\overrides.real.yaml

    mkdir "config\presets" 2>nul

    >"config\presets\overrides.real.yaml" (

        echo # Configuration REAL Empire Agent IA

        echo dry_run: false

        echo mode: "REAL"

        echo log_level: "INFO"

    )

)



if not exist "data" mkdir data

if not exist "data\whales_decisions.csv" (

    echo ts,wallet,symbol,side,trust_score,signal_score,lots,sl,tp,latency_ms,reason,source> "data\whales_decisions.csv"

)



echo.

echo ========================================

echo   DEMARRAGE EMPIRE AGENT IA - MODE REAL

echo ========================================

echo Python  : %PY%

echo Symbols : %SYMBOLS%

echo Mode    : %MODE%

echo LogLevel: %LOG_LEVEL%

echo.



echo [INFO] Demarrage Orchestrator...

start "Empire Orchestrator [REAL]" "%PY%" scripts\start_empire.py --config config/config.yaml --overrides config/presets/overrides.real.yaml --symbols %SYMBOLS%



echo [INFO] Demarrage Scheduler...

if exist "scheduler_empire.py" (

    start "Empire Scheduler [REAL]" "%PY%" scheduler_empire.py --mode %MODE% --log-level %LOG_LEVEL%

) else (

    echo [WARN] scheduler_empire.py introuvable.

)



echo [INFO] Dashboards desactives : aucun lancement.



echo.

echo Empire Agent IA lance (mode REAL).

echo Health monitor : http://localhost:9108/healthz

echo.

pause



endlocal

goto :EOF

