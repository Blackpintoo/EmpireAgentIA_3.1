@echo off
chcp 65001 >nul
echo.
echo 🔍 Recherche de toutes les installations Python sur ce PC...
echo ------------------------------------------------------------

rem Cherche tous les python.exe sur C: (peut prendre quelques secondes)
for /f "delims=" %%P in ('where /r C:\ python.exe 2^>nul') do (
    echo ✅ %%P
)

echo ------------------------------------------------------------
echo 📌 Copiez le chemin complet ci-dessus pour l'ajouter dans votre start_all_auto.bat
echo   Exemple :
echo   set "FORCE_PY=C:\Users\Kévin\AppData\Local\Programs\Python\Python313\python.exe"
echo ------------------------------------------------------------
pause
$