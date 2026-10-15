$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
& '.venv/Scripts/python.exe' -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependências de voz.' }
& '.venv/Scripts/python.exe' scripts/setup_voice.py
if ($LASTEXITCODE -ne 0) { throw 'Preparação da voz local falhou.' }
