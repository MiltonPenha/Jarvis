@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run_jarvis.py %*
) else (
  python run_jarvis.py %*
)
if errorlevel 1 (
  echo.
  echo Nao foi possivel iniciar o JARVIS. Confira a mensagem acima.
  pause
)
