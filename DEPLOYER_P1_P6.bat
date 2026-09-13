@echo off
setlocal
title Deploiement correctifs P1-P6

cd /d "%~dp0"

echo.
echo ==========================================================
echo   CORRECTIFS P1 A P6 - BRANCHE fix-audit-p1-p7
echo ==========================================================
echo.
echo Dossier courant : %CD%
echo.

if not exist ".git" goto :pas_bon_dossier
if not exist "_transfert\fix-audit-p1-p6.bundle" goto :pas_de_bundle

echo [1/5] Nettoyage des verrous git perimes
tasklist /fi "imagename eq git.exe" 2>nul | find /i "git.exe" >nul
if not errorlevel 1 goto :git_en_cours
if exist ".git\index.lock"               del /f /q ".git\index.lock"
if exist ".git\HEAD.lock"                del /f /q ".git\HEAD.lock"
if exist ".git\packed-refs.lock"         del /f /q ".git\packed-refs.lock"
if exist ".git\config.lock"              del /f /q ".git\config.lock"
echo       OK.
echo.

echo [2/5] Etat actuel du depot
git rev-parse --abbrev-ref HEAD
git log -1 --format="      %%h  %%ad  %%s" --date=short
echo.

echo [3/5] Verification des fichiers suivis
git status --porcelain --untracked-files=no > "%TEMP%\empire_st.txt" 2>&1
for %%A in ("%TEMP%\empire_st.txt") do if %%~zA GTR 0 goto :arbre_sale
echo       OK, rien de non sauvegarde.
echo.

echo [4/5] Import de la branche de correctifs
git rev-parse --verify --quiet fix-audit-p1-p7 >nul
if not errorlevel 1 (
    echo       Deja importee, on passe.
) else (
    git fetch "_transfert\fix-audit-p1-p6.bundle" fix-audit-p1-p7:fix-audit-p1-p7
    if errorlevel 1 goto :echec_fetch
    echo       OK.
)
echo.

echo [5/5] Basculement
echo.
echo       Contenu : P1 suite de tests verte + garde-fou de demarrage,
echo                 P2 extraction des gardes, P3 score composite,
echo                 P4 validations ATR, P5 cloisonnement par compte,
echo                 P6 archivage de 19 modules morts.
echo.
echo       Appuie sur une touche pour continuer,
echo       ou ferme cette fenetre pour tout annuler.
pause >nul
git checkout fix-audit-p1-p7
if errorlevel 1 goto :echec_checkout
echo.
git rev-parse --abbrev-ref HEAD
git log -1 --format="      %%h  %%ad  %%s" --date=short
echo.

echo ==========================================================
echo   ETAPE SUIVANTE OBLIGATOIRE
echo ==========================================================
echo.
echo   1. Lance la suite de tests :
echo        .venv\Scripts\python.exe -m pytest tests -q
echo      Elle doit afficher 97 passed, 2 xfailed.
echo      Le bot REFUSE de demarrer si elle ne passe pas.
echo.
echo   2. Verifie que MT5_ACCOUNT est bien dans ton .env :
echo        MT5_ACCOUNT=25832276
echo      Sans lui, les donnees de performance seront rangees
echo      sous compte_inconnu.
echo.
echo   3. L'historique de performance repart de zero sur le
echo      nouveau compte. C'est voulu. Pour reprendre l'ancien :
echo        .venv\Scripts\python.exe tools\adopter_historique_compte.py
echo      (simulation ; ajoute --appliquer pour confirmer)
echo.
echo   4. Pousser sur GitHub ? (O = oui, N = non)
choice /c ON /n >nul
if errorlevel 2 goto :fin
git push -u origin fix-audit-p1-p7
goto :fin

:git_en_cours
echo [ARRET] Un processus git.exe tourne deja sur cette machine.
echo Ferme-le puis relance ce script.
goto :fin

:pas_bon_dossier
echo [ERREUR] Aucun depot git dans ce dossier.
echo Le fichier doit se trouver directement dans C:\EmpireAgentIA_3
goto :fin

:pas_de_bundle
echo [ERREUR] Fichier _transfert\fix-audit-p1-p6.bundle introuvable.
goto :fin

:arbre_sale
echo [ARRET] Modifications non sauvegardees detectees :
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
goto :fin

:fin
echo.
echo ==========================================================
echo   Termine. Appuie sur une touche pour fermer.
echo ==========================================================
pause >nul
endlocal
