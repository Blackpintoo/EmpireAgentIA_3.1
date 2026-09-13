@echo off
setlocal
title Commit P3
cd /d "%~dp0"

echo.
echo ==========================================================
echo   P3 : CORRECTION DU CALCUL DU R + INSTRUMENTATION MFE/MAE
echo ==========================================================
echo.

if not exist ".git" goto :pas_bon_dossier

echo [1/4] Nettoyage des verrous git perimes
tasklist /fi "imagename eq git.exe" 2>nul | find /i "git.exe" >nul
if not errorlevel 1 goto :git_en_cours
if exist ".git\index.lock"               del /f /q ".git\index.lock"
if exist ".git\HEAD.lock"                del /f /q ".git\HEAD.lock"
if exist ".git\packed-refs.lock"         del /f /q ".git\packed-refs.lock"
if exist ".git\objects\maintenance.lock" del /f /q ".git\objects\maintenance.lock"
echo       OK.
echo.

echo [2/4] Verification que le fichier compile
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m py_compile utils\position_manager.py
) else (
    python -m py_compile utils\position_manager.py
)
if errorlevel 1 goto :echec_compile
echo       OK, aucune erreur de syntaxe.
echo.

echo [3/4] Ce qui va etre commite
git diff --stat -- utils/position_manager.py
echo.
echo       Attendu : environ 106 lignes sur 1 fichier.
echo.
echo       Appuie sur une touche pour commiter, ou ferme pour annuler.
pause >nul
git add -- utils/position_manager.py
git commit -F "_transfert\msg_p3.txt"
if errorlevel 1 goto :echec_commit
echo.
git log -1 --format="      %%h  %%s"
echo.

echo [4/4] Push vers GitHub
echo       Pousser maintenant ? (O = oui, N = non)
choice /c ON /n >nul
if errorlevel 2 goto :fin
git push origin reconcilie
if errorlevel 1 echo       [ATTENTION] Push echoue. Reessaie : git push origin reconcilie
goto :fin

:git_en_cours
echo [ARRET] Un processus git.exe tourne deja.
goto :fin

:pas_bon_dossier
echo [ERREUR] Lance ce script depuis C:\EmpireAgentIA_3
goto :fin

:echec_compile
echo [ERREUR] Le fichier ne compile pas. RIEN n'a ete commite.
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
