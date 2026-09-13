@echo off
setlocal
title Deploiement EmpireAgentIA

cd /d "%~dp0"

echo.
echo ==========================================================
echo   DEPLOIEMENT DE LA BRANCHE RECONCILIEE
echo ==========================================================
echo.
echo Dossier courant : %CD%
echo.

if not exist ".git" goto :pas_bon_dossier
if not exist "_transfert\reconcilie.bundle" goto :pas_de_bundle

echo [1/6] Nettoyage des verrous git perimes
tasklist /fi "imagename eq git.exe" 2>nul | find /i "git.exe" >nul
if not errorlevel 1 goto :git_en_cours
if exist ".git\index.lock"                  del /f /q ".git\index.lock"
if exist ".git\HEAD.lock"                   del /f /q ".git\HEAD.lock"
if exist ".git\packed-refs.lock"            del /f /q ".git\packed-refs.lock"
if exist ".git\config.lock"                 del /f /q ".git\config.lock"
if exist ".git\objects\maintenance.lock"    del /f /q ".git\objects\maintenance.lock"
echo       OK.
echo.

echo [2/6] Etat actuel du depot
git rev-parse --abbrev-ref HEAD
git log -1 --format="      %%h  %%ad  %%s" --date=short
echo.

echo [3/6] Verification des fichiers suivis
git status --porcelain --untracked-files=no > "%TEMP%\empire_st.txt" 2>&1
for %%A in ("%TEMP%\empire_st.txt") do if %%~zA GTR 0 goto :arbre_sale
echo       OK, rien de non sauvegarde.
echo.

echo [4/6] Import de la branche reconciliee
git rev-parse --verify --quiet reconcilie >nul
if not errorlevel 1 (
    echo       Deja importee, on passe.
) else (
    git fetch "_transfert\reconcilie.bundle" reconcilie:reconcilie
    if errorlevel 1 goto :echec_fetch
    echo       OK.
)
echo.

echo [5/6] Basculement sur la branche reconciliee
echo.
echo       Tu vas recuperer 3 mois de correctifs (mars a mai 2026).
echo       orchestrator.py passe de 5157 a 6152 lignes.
echo.
echo       Appuie sur une touche pour continuer,
echo       ou ferme cette fenetre pour tout annuler.
pause >nul
git checkout reconcilie
if errorlevel 1 goto :echec_checkout
echo.
echo       OK. Branche active :
git rev-parse --abbrev-ref HEAD
git log -1 --format="      %%h  %%ad  %%s" --date=short
echo.

echo [6/6] Sauvegarde sur GitHub
echo.
echo       Tant que ce n'est pas pousse, ton travail n'existe que sur ce disque.
echo       Pousser maintenant les deux branches ? (O = oui, N = non)
choice /c ON /n >nul
if errorlevel 2 goto :fin
echo.
echo       --- reconcilie ---
git push -u origin reconcilie
echo.
echo       --- local-mars-2026 ---
git push -u origin local-mars-2026
echo.
git branch -D tmp-code >nul 2>&1
git branch -D tmp-launcher >nul 2>&1
goto :fin

:git_en_cours
echo [ARRET] Un processus git.exe tourne deja sur cette machine.
echo Ferme-le (ou attends qu'il se termine) puis relance ce script.
goto :fin

:pas_bon_dossier
echo [ERREUR] Aucun depot git trouve dans ce dossier.
echo Le fichier doit se trouver directement dans C:\EmpireAgentIA_3
echo Dossier ou il a ete lance : %CD%
goto :fin

:pas_de_bundle
echo [ERREUR] Fichier _transfert\reconcilie.bundle introuvable.
goto :fin

:arbre_sale
echo [ARRET] Des modifications non sauvegardees ont ete detectees :
echo.
type "%TEMP%\empire_st.txt"
echo.
echo Rien n'a ete modifie. Signale-le a Claude avant de continuer.
goto :fin

:echec_fetch
echo [ERREUR] L'import depuis le bundle a echoue. Rien n'a ete modifie.
goto :fin

:echec_checkout
echo [ERREUR] Le basculement a echoue. Ton etat actuel est intact.
echo Verifie avec : git status
goto :fin

:fin
echo.
echo ==========================================================
echo   Termine. Appuie sur une touche pour fermer.
echo ==========================================================
pause >nul
endlocal
