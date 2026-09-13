@echo off
setlocal
title Complement P5 - journal MFE/MAE

cd /d "%~dp0"

echo.
echo ==========================================================
echo   COMPLEMENT P5 - 1 commit manquant
echo ==========================================================
echo.
echo   Ce commit a ete ecrit apres la creation du premier
echo   bundle : il n'y figurait pas.
echo.
echo   Contenu : data\trade_mfe.csv suit desormais la meme
echo   regle que les autres donnees de performance
echo   (data\compte_<numero>\trade_mfe.csv), et les dossiers
echo   par compte sortent du versionnement.
echo.

if not exist ".git" goto :pas_bon_dossier
if not exist "_transfert\complement-p5-mfe.bundle" goto :pas_de_bundle

echo [1/4] Nettoyage des verrous git perimes
tasklist /fi "imagename eq git.exe" 2>nul | find /i "git.exe" >nul
if not errorlevel 1 goto :git_en_cours
if exist ".git\index.lock"        del /f /q ".git\index.lock"
if exist ".git\HEAD.lock"         del /f /q ".git\HEAD.lock"
if exist ".git\config.lock"       del /f /q ".git\config.lock"
echo       OK.
echo.

echo [2/4] Verification de la branche courante
git rev-parse --abbrev-ref HEAD > "%TEMP%\empire_br.txt"
set /p BRANCHE=<"%TEMP%\empire_br.txt"
echo       Branche : %BRANCHE%
if not "%BRANCHE%"=="fix-audit-p1-p7" goto :mauvaise_branche
echo.

echo [3/4] Verification des fichiers de CODE
git status --porcelain --untracked-files=no -- . ":(exclude)data" ":(exclude)reports" > "%TEMP%\empire_st.txt" 2>&1
for %%A in ("%TEMP%\empire_st.txt") do if %%~zA GTR 0 goto :code_sale
echo       OK.
echo.

echo [4/4] Application du commit
git pull "_transfert\complement-p5-mfe.bundle" fix-audit-p1-p7
if errorlevel 1 goto :echec_pull
echo.
git log -1 --format="      %%h  %%ad  %%s" --date=short
echo.
echo       Pousser sur GitHub ? (O = oui, N = non)
choice /c ON /n >nul
if errorlevel 2 goto :fin
git push origin fix-audit-p1-p7
goto :fin

:git_en_cours
echo [ARRET] Un processus git.exe tourne deja. Ferme-le et relance.
goto :fin

:mauvaise_branche
echo [ARRET] Tu n'es pas sur fix-audit-p1-p7. Rien n'a ete modifie.
echo Bascule d'abord avec : git checkout fix-audit-p1-p7
goto :fin

:pas_bon_dossier
echo [ERREUR] Aucun depot git dans ce dossier.
goto :fin

:pas_de_bundle
echo [ERREUR] _transfert\complement-p5-mfe.bundle introuvable.
goto :fin

:code_sale
echo [ARRET] Des fichiers de CODE sont modifies :
echo.
type "%TEMP%\empire_st.txt"
echo.
echo Rien n'a ete modifie. Signale-le a Claude.
goto :fin

:echec_pull
echo [ERREUR] L'application a echoue. Ton etat est intact.
echo Copie le message ci-dessus et envoie-le a Claude.
goto :fin

:fin
echo.
echo ==========================================================
echo   Termine. Appuie sur une touche pour fermer.
echo ==========================================================
pause >nul
endlocal
