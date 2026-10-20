@echo off
cd /d "%~dp0"
echo Iniciando o JARVIS. Aguarde o servidor ficar pronto...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -u run_jarvis.py %*
) else (
  python -u run_jarvis.py %*
)
if errorlevel 1 (
  echo.
  echo Nao foi possivel iniciar o JARVIS. Confira a mensagem acima.
  pause
)
