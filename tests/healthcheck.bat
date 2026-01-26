@echo off
rem  start-empire.cmd — Lancer EmpireAgentIA en un clic (auto-venv + install + run)
setlocal enableextensions enabledelayedexpansion

rem ─────────────────────────────────────────────────────────────────────────────
rem Aller à la racine (où se trouve ce .cmd) + UTF-8 pour les chemins/accents
rem ─────────────────────────────────────────────────────────────────────────────
cd /d "%~dp0"
chcp 65001 >nul 2>&1

set "ROOT=%CD%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%ROOT%"

rem Logs
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs" >nul 2>&1
for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set "TODAY=%%c-%%b-%%a"
for /f "tokens=1 delims=." %%h in ('time /t') do set "NOW=%%h"
set "NOW=%NOW::=-%"
set "LOGFILE=%ROOT%\logs\empire_%TODAY%_%NOW%.log"

rem Vérifs de base
if not exist "%ROOT%\orchestrator\orchestrator.py" (
  echo [ERREUR] Fichier "orchestrator\orchestrator.py" introuvable dans %ROOT%.
  echo Assure-toi d'executer ce script depuis la racine du projet.
  echo.
  pause
  exit /b 1
)

rem ─────────────────────────────────────────────────────────────────────────────
rem 1) Choisir un Python pour créer le venv s’il n’existe pas
rem ─────────────────────────────────────────────────────────────────────────────
set "PY_BOOT="
where py >nul 2>&1 && set "PY_BOOT=py"
if not defined PY_BOOT (
  where python >nul 2>&1 && set "PY_BOOT=python"
)

if not defined PY_BOOT (
  echo [ERREUR] Aucun interprete Python trouve dans PATH. Installe Python 3.12+.
  echo https://www.python.org/downloads/windows/
  echo.
  pause
  exit /b 1
)

rem ─────────────────────────────────────────────────────────────────────────────
rem 2) Créer venv si absent
rem ─────────────────────────────────────────────────────────────────────────────
if not exist "%ROOT%\.venv\Scripts\python.exe" (
  echo [SETUP] Creation de l'environnement virtuel .venv ...
  if /i "%PY_BOOT%"=="py" (
    py -3.12 -m venv ".venv"
    if errorlevel 1 (
      echo [WARN] py -3.12 indisponible, tentative py -3.11
      py -3.11 -m venv ".venv"
    )
  ) else (
    python -m venv ".venv"
  )
  if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo [ERREUR] Echec de creation du venv. Verifie ta version de Python.
    echo.
    pause
    exit /b 1
  )
)

set "PY=%ROOT%\.venv\Scripts\python.exe"

rem ─────────────────────────────────────────────────────────────────────────────
rem 3) Mettre pip a jour et installer les dependances (sans cache, ≈ moins d’ennuis)
rem ─────────────────────────────────────────────────────────────────────────────
echo [SETUP] Upgrade pip ...
"%PY%" -m pip install --upgrade pip >> "%LOGFILE%" 2>&1

if exist "%ROOT%\requirements.txt" (
  echo [SETUP] Installation des dependances (requirements.txt) ...
  "%PY%" -m pip install --no-cache-dir -r "%ROOT%\requirements.txt" >> "%LOGFILE%" 2>&1
  if errorlevel 1 (
    echo [WARN] Installation avec --no-cache-dir a echoue, nouvelle tentative classique...
    "%PY%" -m pip install -r "%ROOT%\requirements.txt" >> "%LOGFILE%" 2>&1
  )
) else (
  echo [WARN] requirements.txt introuvable. On continue quand meme.
)

rem ─────────────────────────────────────────────────────────────────────────────
rem 4) Healthcheck rapide (config + MT5 + prix)
rem ─────────────────────────────────────────────────────────────────────────────
echo [CHECK] Verification de la config et de MT5...
"%PY%" - <<PY 1>>"%LOGFILE%" 2>&1
import sys
from utils.config import load_config, get_enabled_symbols
from utils.mt5_client import MT5Client

print("=== HEALTHCHECK ===")
cfg = load_config()
print("cfg loaded:", bool(cfg))
print("enabled_symbols:", get_enabled_symbols())

MT5Client.initialize_if_needed()
cli = MT5Client()
ai = cli.get_account_info()
print("mt5.login:", bool(ai))
if ai:
    print("login:", getattr(ai, "login", None), "server:", getattr(ai, "server", None))

for s in get_enabled_symbols():
    try:
        cli.ensure_symbol(s)
        px = cli.get_last_price(s)
        print(f"{s} price:", px)
    except Exception as e:
        print(f"{s} error:", e)
PY

type "%LOGFILE%" | find /i "mt5.login: True" >nul
if errorlevel 1 (
  echo [WARN] MT5 non connecte (ou inaccessible). Verifie config/config.yaml ^(section mt5^).
  echo Voir "%LOGFILE%" pour le detail.
  echo.
  choice /c YN /n /m "Continuer quand meme ? (Y/N) "
  if errorlevel 2 exit /b 1
)

rem ─────────────────────────────────────────────────────────────────────────────
rem 5) Recuperer les symboles actifs depuis profiles.yaml
rem ─────────────────────────────────────────────────────────────────────────────
set "SYMBOLS="
for /f "usebackq delims=" %%S in (`"%PY%" -c "from utils.config import get_enabled_symbols; print(' '.join(get_enabled_symbols()))"`) do (
  set "SYMBOLS=%%S"
)

if "%SYMBOLS%"=="" (
  echo [WARN] Aucun symbole actif dans config\profiles.yaml (cle enabled_symbols). On lancera sans filtre.
) else (
  echo [INFO] Symboles actifs: %SYMBOLS%
)

rem ─────────────────────────────────────────────────────────────────────────────
rem 6) Lancement de l'orchestrateur
rem ─────────────────────────────────────────────────────────────────────────────
title EmpireAgentIA - Orchestrator
echo.
echo ▶ Lancement EmpireAgentIA
echo    Dossier  : %ROOT%
echo    Python   : %PY%
if "%SYMBOLS%"=="" (
  echo    Arguments: -W ignore::RuntimeWarning -m orchestrator.orchestrator
) else (
  echo    Arguments: -W ignore::RuntimeWarning -m orchestrator.orchestrator --symbols %SYMBOLS%
)
echo    Logs     : %LOGFILE%
echo.

if "%SYMBOLS%"=="" (
  "%PY%" -W ignore::RuntimeWarning -m orchestrator.orchestrator 1>>"%LOGFILE%" 2>&1
) else (
  "%PY%" -W ignore::RuntimeWarning -m orchestrator.orchestrator --symbols %SYMBOLS% 1>>"%LOGFILE%" 2>&1
)

set "EC=%ERRORLEVEL%"
echo.
if %EC% NEQ 0 (
  echo ✖ Terminé avec code %EC%.
  echo [TIP] Ouvre le fichier de logs: "%LOGFILE%"
) else (
  echo ✔ Terminé.
)
echo.
pause
endlocal
exit /b %EC%
