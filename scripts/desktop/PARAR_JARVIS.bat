@echo off
title PARAR JARVIS
call "%~dp0jarvis\stop_jarvis.bat"
if errorlevel 1 (
  echo Nao foi possivel concluir o encerramento. Confira a mensagem acima.
  pause
  exit /b 1
)
timeout /t 2 >nul
