@echo off
rem  start-empire-weekend.cmd  —  Week-end Crypto (ultra-agressif)
setlocal ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION

cd /d "%~dp0"
chcp 65001 >nul 2>nul

rem --- dossier logs ---
set "LOGDIR=%CD%\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1
set "LOG=%LOGDIR%\start-empire-weekend.log"

echo [ %DATE% %TIME% ] --- Lancement start-empire-weekend --- >> "%LOG%"

rem --- détection Python (venv > Python312 > python > py -3.12) ---
set "PY="
if exist "%CD%\.venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do set "PY=%%P"
if not defined PY for /f "delims=" %%P in ('where py 2^>nul') do set "PY=%%P -3.12"
if not defined PY (
  echo ❌ Python introuvable. Installe Python 3.12 ou active le venv. | tee >> "%LOG%"
  goto :PAUSE_AND_EXIT
)

set "PYTHONUTF8=1"
set "PYTHONPATH=%CD%"

rem --- appliquer le preset week-end ---
if not exist "config\presets\overrides.weekend.yaml" (
  echo ❌ Fichier "config\presets\overrides.weekend.yaml" introuvable. >> "%LOG%"
  echo ❌ Le preset week-end est manquant : config\presets\overrides.weekend.yaml
  goto :PAUSE_AND_EXIT
)

if exist "config\overrides.yaml" copy /y "config\overrides.yaml" "config\overrides.backup.yaml" >nul
copy /y "config\presets\overrides.weekend.yaml" "config\overrides.yaml" >nul
echo ✅ Preset appliqué: WEEK-END CRYPTO (ultra-agressif) >> "%LOG%"

rem --- symboles (par défaut BTC+LINK, sinon ceux passés en argument) ---
set "SYMS=BTCUSD LINKUSD"
if not "%~1"=="" set "SYMS=%*"

set "ARGS=-W ignore::RuntimeWarning -m orchestrator.orchestrator --symbols %SYMS%"

echo ▶ Lancement Empire (Week-end)
echo    Python  : %PY%
echo    Dossier : %CD%
echo    Symboles: %SYMS%
echo ▶ CMD : "%PY%" %ARGS% >> "%LOG%"

"%PY%" %ARGS%
set "RC=%ERRORLEVEL%"
echo [ %DATE% %TIME% ] --- Fin (RC=%RC%) --- >> "%LOG%"

:PAUSE_AND_EXIT
if /I "%1"=="--nopause" exit /b %RC%
echo.
echo (Le script reste ouvert pour afficher les messages.)
echo Appuie sur une touche pour fermer...
pause >nul
exit /b %RC%
