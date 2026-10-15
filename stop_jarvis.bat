@echo off
title PARAR JARVIS
echo Encerrando todos os processos do JARVIS...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run_jarvis*' -or $_.CommandLine -like '*start_jarvis*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo JARVIS foi totalmente finalizado.
timeout /t 2 >nul
