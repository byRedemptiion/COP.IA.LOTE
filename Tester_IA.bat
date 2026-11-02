@echo off
cd /d "%~dp0"
echo Test de la connexion a l IA (question texte, sans image)...
echo.
".venv\Scripts\alicia-diag.exe" ping
echo.
pause
