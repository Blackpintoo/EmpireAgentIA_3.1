@echo off
setlocal
title Correctif flux d'actualite

cd /d "%~dp0"

echo.
echo ==========================================================
echo   CORRECTIF : FLUX D'ACTUALITE (flux mort + tri du bruit)
echo ==========================================================
echo.
echo   ARRETE LE BOT avant de continuer.
echo.

if not exist ".git" goto :pas_bon_dossier
if not exist "_transfert\news.bundle" goto :pas_de_bundle

echo [1/4] Nettoyage des verrous git perimes
tasklist /fi "imagename eq git.exe" 2>nul | find /i "git.exe" >nul
if not errorlevel 1 goto :git_en_cours
if exist ".git\index.lock"        del /f /q ".git\index.lock"
if exist ".git\HEAD.lock"         del /f /q ".git\HEAD.lock"
if exist ".git\packed-refs.lock"  del /f /q ".git\packed-refs.lock"
if exist ".git\config.lock"       del /f /q ".git\config.lock"
echo       OK.
echo.

echo [2/4] Verification de la branche
git rev-parse --abbrev-ref HEAD > "%TEMP%\empire_br.txt"
set /p BRANCHE=<"%TEMP%\empire_br.txt"
if not "%BRANCHE%"=="fix-audit-p1-p7" goto :mauvaise_branche
git status --porcelain --untracked-files=no -- . ":(exclude)data" ":(exclude)reports" > "%TEMP%\empire_st.txt" 2>&1
for %%A in ("%TEMP%\empire_st.txt") do if %%~zA GTR 0 goto :code_sale
echo       OK, sur fix-audit-p1-p7, aucun fichier de code modifie.
echo.

echo [3/4] Application du correctif
git fetch "_transfert\news.bundle" fix-audit-p1-p7
if errorlevel 1 goto :echec_fetch
git merge --ff-only FETCH_HEAD
if errorlevel 1 goto :echec_merge
git log -1 --format="      %%h  %%ad  %%s" --date=short
echo.

echo [4/4] Verification
echo.
echo       Suite de tests (attendu : 106 passed)
.venv\Scripts\python.exe -m pytest tests -q --basetemp=.pytest_tmp
echo.
echo       Etat des flux apres correctif (attendu : 27/27 vivants)
.venv\Scripts\python.exe tools\test_news_sources.py --symbol AUDUSD
echo.
echo       Pousser sur GitHub ? (O = oui, N = non)
choice /c ON /n >nul
if errorlevel 2 goto :fin
git push origin fix-audit-p1-p7
goto :fin

:git_en_cours
echo [ARRET] Un processus git.exe tourne deja. Ferme-le puis relance.
goto :fin

:pas_bon_dossier
echo [ERREUR] Aucun depot git dans ce dossier.
goto :fin

:pas_de_bundle
echo [ERREUR] Fichier _transfert\news.bundle introuvable.
goto :fin

:mauvaise_branche
echo [ARRET] Branche actuelle : %BRANCHE%
echo Ce correctif s'applique sur fix-audit-p1-p7. Rien n'a ete modifie.
goto :fin

:code_sale
echo [ARRET] Des fichiers de CODE sont modifies :
echo.
type "%TEMP%\empire_st.txt"
echo.
echo Rien n'a ete modifie. Signale-le a Claude.
goto :fin

:echec_fetch
echo [ERREUR] L'import depuis le bundle a echoue. Rien n'a ete modifie.
goto :fin

:echec_merge
echo [ERREUR] La mise a jour a echoue. Ton etat actuel est intact.
goto :fin

:fin
echo.
echo ==========================================================
echo   Termine. Appuie sur une touche pour fermer.
echo ==========================================================
pause >nul
endlocal
