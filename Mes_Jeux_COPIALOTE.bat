@echo off
rem Profils de jeu de COP'IA'LOTE : jeux reconnus et sites de reference.
cd /d "%~dp0"
".venv\Scripts\alicia-diag.exe" games
start "" notepad "%APPDATA%\Alicia\games.toml"
pause
