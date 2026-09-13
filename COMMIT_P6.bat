@echo off
setlocal
title Commit P6 - sources news
cd /d "%~dp0"

echo.
echo ==========================================================
echo   P6 : SOURCES D'ACTUALITE HIERARCHISEES
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

echo [2/5] Compilation
if exist ".venv\Scripts\python.exe" (
    set PY=.venv\Scripts\python.exe
) else (
    set PY=python
)
%PY% -m py_compile utils\news_sources.py agents\news.py tools\test_news_sources.py
if errorlevel 1 goto :echec_compile
echo       OK.
echo.

echo [3/5] VALIDATION DES FLUX (necessite Internet, ~30 s)
echo       C'est l'etape importante : je n'ai pas pu tester les flux
echo       depuis le conteneur, son reseau est restreint.
echo.
%PY% tools\test_news_sources.py --symbol NAS100 --skip-health
echo.
%PY% tools\test_news_sources.py --symbol BTCUSD --skip-health
echo.
echo       Note les flux MORTS et signale-les a Claude.
echo.
pause

echo [4/5] Ce qui va etre commite
git status --porcelain -- utils/news_sources.py agents/news.py tools/test_news_sources.py
git diff --stat -- agents/news.py
echo.
echo       Appuie sur une touche pour commiter, ou ferme pour annuler.
pause >nul
git add -- utils/news_sources.py agents/news.py tools/test_news_sources.py
git commit -F "_transfert\msg_p6.txt"
if errorlevel 1 goto :echec_commit
echo.
git log -1 --format="      %%h  %%s"
echo.

echo [5/5] Push vers GitHub
echo       Pousser maintenant ? (O = oui, N = non)
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

:echec_compile
echo [ERREUR] Compilation echouee. RIEN n'a ete commite.
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
