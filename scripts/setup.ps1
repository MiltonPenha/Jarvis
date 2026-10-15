param([switch]$SkipHermes)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar o ambiente Python do JARVIS.' }
}
$taskRequirements=if (Test-Path -LiteralPath 'requirements.lock.txt') { 'requirements.lock.txt' } else { 'requirements.txt' }
& '.venv/Scripts/python.exe' -m pip install -r $taskRequirements
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependências do JARVIS.' }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
if (-not $SkipHermes) {
    if (-not (Test-Path -LiteralPath '.runtime/hermes-agent/run_agent.py')) {
        New-Item -ItemType Directory -Force -Path '.runtime/hermes-agent' | Out-Null
        git -C .runtime/hermes-agent init
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar checkout isolado do Hermes.' }
        $taskRemote=git -C .runtime/hermes-agent remote get-url origin 2>$null
        if (-not $taskRemote) { git -C .runtime/hermes-agent remote add origin https://github.com/NousResearch/hermes-agent.git }
        elseif ($taskRemote -ne 'https://github.com/NousResearch/hermes-agent.git') { throw 'O checkout Hermes aponta para um remoto diferente do oficial.' }
        git -C .runtime/hermes-agent fetch --depth 1 origin 7bda2a3368024f7ae1c70cef16583e7c2c891674
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao obter a revisão oficial do Hermes.' }
        git -C .runtime/hermes-agent checkout --detach FETCH_HEAD
        if ($LASTEXITCODE -ne 0) { throw 'Não foi possível selecionar a revisão verificada do Hermes.' }
    }
    $env:HERMES_HOME=Join-Path $taskRoot '.data/hermes'
    $env:HERMES_RUNTIME_DIR=Join-Path $taskRoot '.runtime/tools'
    # Isolates bootstrap Python and avoids the machine's existing uv minor link.
    $env:UV_PYTHON_INSTALL_DIR=Join-Path $taskRoot '.runtime/bootstrap-python'
    $env:UV_PYTHON_INSTALL_BIN='false'
    & '.runtime/hermes-agent/setup-hermes.ps1' -RuntimeOnly
    if ($LASTEXITCODE -ne 0) { throw 'A preparação oficial do Hermes falhou.' }
}
& '.venv/Scripts/python.exe' -m core.hermes_runtime
if ($LASTEXITCODE -ne 0) { throw 'Runtime Hermes não selecionado.' }
Write-Host 'Pronto. Inicie com start_jarvis.bat. Configure as chaves somente no backend.'
