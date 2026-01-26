@echo off
REM ============================================================================
REM  EMPIRE AGENT IA v3 - LANCEMENT WINDOWS
REM ============================================================================
REM  Script de lancement avec profils SCALPING/SWING
REM  Date: 2025-12-07
REM
REM  Usage:
REM    - Double-cliquer sur ce fichier
REM    OU
REM    - Executer depuis PowerShell/CMD
REM
REM  Profils de trading:
REM    - SCALPING : M5/M15/M30 (defaut)
REM    - SWING    : H1/H4/D1
REM
REM  Mode:
REM    - Voir .env pour MT5_DRY_RUN (0=REAL, 1=SIMULATION)
REM ============================================================================

setlocal EnableExtensions EnableDelayedExpansion

REM Aller dans le repertoire du script
cd /d "%~dp0"

echo.
echo ============================================================================
echo   EMPIRE AGENT IA v3 - DEMARRAGE
echo   Date: %DATE% %TIME%
echo ============================================================================
echo.

REM ============================================================================
REM ETAPE 1 : Verifier Python
REM ============================================================================

echo [1/6] Verification Python...

REM Chercher Python dans differents emplacements
set "PYTHON_CMD="

REM 1. Environnement virtuel .venv (Windows)
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
    echo   [OK] Python trouve dans .venv
    goto :python_found
)

REM 2. Environnement virtuel venv (WSL)
if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=venv\Scripts\python.exe"
    echo   [OK] Python trouve dans venv
    goto :python_found
)

REM 3. Python systeme
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PYTHON_CMD=python"
    echo   [OK] Python systeme trouve
    goto :python_found
)

REM Python non trouve
echo   [ERREUR] Python non trouve !
echo.
echo   Solutions:
echo   1. Installer Python depuis https://www.python.org/downloads/
echo   2. Cocher "Add Python to PATH" pendant installation
echo   3. OU creer environnement virtuel:
echo      python -m venv .venv
echo.
pause
exit /b 1

:python_found

REM ============================================================================
REM ETAPE 2 : Verifier dependances
REM ============================================================================

echo [2/6] Verification dependances Python...

REM Verifier si pandas est installe
%PYTHON_CMD% -c "import pandas" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [WARN] Dependances manquantes - Installation requise
    echo.
    echo   Voulez-vous installer les dependances maintenant ? (O/N^)
    set /p INSTALL_DEPS=

    if /i "!INSTALL_DEPS!"=="O" (
        echo   Installation des dependances...
        %PYTHON_CMD% -m pip install -r requirements.txt

        if %ERRORLEVEL% NEQ 0 (
            echo   [ERREUR] Installation echouee
            pause
            exit /b 1
        )
        echo   [OK] Dependances installees
    ) else (
        echo   [ERREUR] Dependances requises pour continuer
        pause
        exit /b 1
    )
) else (
    echo   [OK] Dependances presentes
)

REM ============================================================================
REM ETAPE 3 : Verifier configuration
REM ============================================================================

echo [3/6] Verification configuration...

REM Verifier .env
if not exist ".env" (
    echo   [WARN] Fichier .env manquant

    if exist ".env.example" (
        echo   Creation de .env depuis .env.example...
        copy ".env.example" ".env" >nul
        echo   [OK] Fichier .env cree
        echo.
        echo   IMPORTANT: Editez .env pour ajouter vos API keys:
        echo   - FINNHUB_API_KEY
        echo   - ALPHA_VANTAGE_API_KEY
        echo   - MT5 credentials
        echo.
        echo   Appuyez sur une touche pour continuer...
        pause >nul
    ) else (
        echo   [ERREUR] .env.example introuvable
        pause
        exit /b 1
    )
) else (
    echo   [OK] Fichier .env present
)

REM Verifier config.yaml
if not exist "config\config.yaml" (
    echo   [ERREUR] config\config.yaml introuvable
    pause
    exit /b 1
)
echo   [OK] Configuration presente

REM ============================================================================
REM ETAPE 4 : Verifier MetaTrader 5
REM ============================================================================

echo [4/6] Verification MetaTrader 5...

%PYTHON_CMD% -c "import MetaTrader5" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   [WARN] MetaTrader5 module non installe
    echo.
    echo   Voulez-vous installer MetaTrader5 ? (O/N^)
    echo   Note: Requis pour trading REEL, pas pour tests API
    set /p INSTALL_MT5=

    if /i "!INSTALL_MT5!"=="O" (
        echo   Installation MetaTrader5...
        %PYTHON_CMD% -m pip install MetaTrader5

        if %ERRORLEVEL% EQU 0 (
            echo   [OK] MetaTrader5 installe
        ) else (
            echo   [WARN] Installation echouee - Mode simulation uniquement
        )
    ) else (
        echo   [INFO] Mode simulation uniquement (sans MT5^)
    )
) else (
    echo   [OK] MetaTrader5 disponible
)

REM ============================================================================
REM ETAPE 5 : Verification des nouveaux profils
REM ============================================================================

echo [5/6] Verification profils de trading...

%PYTHON_CMD% -c "from config.trading_profiles import PROFILES_AVAILABLE; print('OK' if PROFILES_AVAILABLE else 'FALLBACK')" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   [OK] Systeme de profils SCALPING/SWING actif
) else (
    echo   [WARN] Profils en mode fallback
)

REM Afficher les symboles actifs
echo.
echo   Symboles actifs (16):
echo   - CRYPTOS  : BTCUSD, ETHUSD, BNBUSD, LTCUSD, ADAUSD, SOLUSD
echo   - FOREX    : EURUSD, GBPUSD, USDJPY, AUDUSD
echo   - INDICES  : DJ30, NAS100, GER40
echo   - COMMODITIES: XAUUSD, XAGUSD, CL-OIL
echo.

REM ============================================================================
REM ETAPE 6 : Selection du profil de trading
REM ============================================================================

echo [6/6] Selection du profil de trading...
echo.
echo   Quel profil souhaitez-vous utiliser ?
echo   1. AUTO - Les deux profils (recommande)
echo      SCALPING pour M5/M15/M30, SWING pour H1/H4/D1
echo   2. SCALPING uniquement (M5/M15/M30)
echo   3. SWING uniquement (H1/H4/D1)
echo.
set "PROFILE_CHOICE=1"
set /p PROFILE_CHOICE=  Choix (1, 2 ou 3, Enter=1):

set "TRADING_PROFILE=AUTO"
if "!PROFILE_CHOICE!"=="2" set "TRADING_PROFILE=SCALPING"
if "!PROFILE_CHOICE!"=="3" set "TRADING_PROFILE=SWING"

if "!TRADING_PROFILE!"=="SCALPING" (
    echo   [OK] Profil SCALPING uniquement - M5/M15/M30
) else if "!TRADING_PROFILE!"=="SWING" (
    echo   [OK] Profil SWING uniquement - H1/H4/D1
) else (
    echo   [OK] Mode AUTO - SCALPING + SWING selon timeframe
)

REM ============================================================================
REM LANCEMENT
REM ============================================================================

echo.
echo ============================================================================

REM Afficher mode
findstr /C:"MT5_DRY_RUN=0" .env >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo.
    echo   ****************************************
    echo   *     MODE : TRADING REEL             *
    echo   *     PROFIL: %TRADING_PROFILE%                 *
    echo   ****************************************
    echo.
    echo   ATTENTION : Trading avec argent reel !
    echo.
    set "MODE_TEXT=REAL"
) else (
    echo.
    echo   ========================================
    echo     MODE : SIMULATION (DRY-RUN^)
    echo     PROFIL: %TRADING_PROFILE%
    echo   ========================================
    echo   Trading en simulation (pas d'argent reel^)
    echo.
    set "MODE_TEXT=DRY-RUN"
)

REM Afficher infos
echo   Python      : %PYTHON_CMD%
echo   Config      : config\config.yaml
echo   Mode        : %MODE_TEXT%
echo   Profil      : %TRADING_PROFILE%
echo   Symboles    : 16 actifs
echo   Health URL  : http://localhost:9108/healthz
echo.
echo ============================================================================
echo.

REM Confirmer lancement
echo   Appuyez sur une touche pour lancer le bot...
echo   (Ctrl+C pour annuler^)
pause >nul

REM Lancer le bot avec la variable d'environnement du profil
echo [INFO] Demarrage du bot en mode %TRADING_PROFILE%...
echo.

set TRADING_PROFILE=%TRADING_PROFILE%
%PYTHON_CMD% main.py

REM Verifier si erreur
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ============================================================================
    echo   [ERREUR] Le bot s'est arrete avec une erreur
    echo ============================================================================
    echo.
    echo   Consultez les logs dans : logs\
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================================
echo   Bot arrete proprement
echo ============================================================================
echo.
pause

endlocal
exit /b 0
