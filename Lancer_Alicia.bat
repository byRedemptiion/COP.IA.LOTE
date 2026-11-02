@echo off
setlocal
cd /d "%~dp0"
rem Lance ALICIA sans terminal. Pour la lancer avec un terminal (diagnostic) :
rem   Lancer_Alicia.bat --console

if not exist ".venv\Scripts\alicia.exe" goto install

rem Nouvelle version : dependances changees (uv.lock) ou lanceur sans terminal absent ?
set "NEED="
fc /b "uv.lock" ".venv\uv.lock.installed" >nul 2>nul || set "NEED=1"
if not exist ".venv\Scripts\alicia-gui.exe" set "NEED=1"
if defined NEED (
  echo Mise a jour des composants de COP'IA'LOTE...
  powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\setup.ps1" -Update
  if errorlevel 1 (
    echo.
    echo La mise a jour a echoue : envoie une capture de cette fenetre.
    pause
    exit /b 1
  )
)
goto run

:install
echo COP'IA'LOTE n'est pas encore installe sur ce PC : lancement de l'installation...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\setup.ps1"
if errorlevel 1 (
  echo.
  echo L'installation a echoue : envoie une capture de cette fenetre.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\alicia.exe" (
  echo Installation incomplete : .venv\Scripts\alicia.exe est introuvable.
  pause
  exit /b 1
)

:run
if /i "%~1"=="--console" (
  ".venv\Scripts\alicia.exe" %2 %3 %4
  if errorlevel 1 pause
  exit /b
)
if exist ".venv\Scripts\alicia-gui.exe" (
  start "" ".venv\Scripts\alicia-gui.exe" %*
) else (
  start "" ".venv\Scripts\alicia.exe" %*
)
exit /b 0
