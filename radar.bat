@echo off
REM Radar Concorsi - avvio rapido
REM Doppio clic per aggiornare i bandi e aprire la dashboard.

cd /d "%~dp0"

echo Aggiornamento bandi dalla Gazzetta Ufficiale...
echo.

py radar_concorsi.py
if errorlevel 1 (
  echo.
  echo Qualcosa non ha funzionato. Leggi il messaggio qui sopra.
  pause
  exit /b 1
)

echo.
echo Apro la dashboard...
start "" "radar_concorsi.html"
timeout /t 3 >nul
