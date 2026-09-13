@echo off
setlocal
title Nettoyage du depot
cd /d "%~dp0"

echo.
echo ==========================================================
echo   NETTOYAGE DU DEPOT
echo   206 fichiers 'modifies', 0 travail a sauver.
echo ==========================================================
echo.

if not exist ".git" goto :pas_bon_dossier

echo [1/5] Nettoyage des verrous git perimes
tasklist /fi "imagename eq git.exe" 2>nul | find /i "git.exe" >nul
if not errorlevel 1 goto :git_en_cours
if exist ".git\index.lock"               del /f /q ".git\index.lock"
if exist ".git\HEAD.lock"                del /f /q ".git\HEAD.lock"
if exist ".git\packed-refs.lock"         del /f /q ".git\packed-refs.lock"
if exist ".git\objects\maintenance.lock" del /f /q ".git\objects\maintenance.lock"
echo       OK.
echo.

echo [2/5] Installation de .gitattributes
copy /y "_transfert\gitattributes.txt" ".gitattributes" >nul
echo       OK.
echo.

echo [3/5] Desindexation des donnees runtime
echo       Les fichiers restent sur le disque, ils sortent seulement du depot.
git rm -r -q --cached data 2>nul
echo       OK.
echo.

echo [4/5] Renormalisation des fins de ligne
git add --renormalize . 2>nul
echo       OK.
echo.
echo       Recapitulatif :
git status --porcelain --untracked-files=no | find /c /v ""
echo       fichier(s) concerne(s).
echo.
echo       Appuie sur une touche pour commiter, ou ferme pour annuler.
pause >nul
git add -A -- .gitattributes .gitignore
git commit -F "_transfert\msg_clean.txt"
if errorlevel 1 goto :echec_commit
echo.
git log -1 --format="      %%h  %%s"
echo.

echo [5/5] Verification : le depot doit etre propre
git status --porcelain --untracked-files=no | find /c /v ""
echo       ligne(s). Zero attendu.
echo.
echo       Pousser vers GitHub ? (O = oui, N = non)
choice /c ON /n >nul
if errorlevel 2 goto :fin
git push origin reconcilie
goto :fin

:git_en_cours
echo [ARRET] Un processus git.exe tourne deja.
goto :fin

:pas_bon_dossier
echo [ERREUR] Lance ce script depuis C:\EmpireAgentIA_3
goto :fin

:echec_commit
echo [ERREUR] Le commit a echoue. Tes fichiers sont intacts.
goto :fin

:fin
echo.
echo ==========================================================
echo   Termine. Appuie sur une touche pour fermer.
echo ==========================================================
pause >nul
endlocal
