param([switch]$Testing)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create Python environment.' }
}
& '.venv/Scripts/python.exe' -m pip install -r engine/requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Cannot install emulator dependencies.' }
if ($Testing) {
    & '.venv/Scripts/python.exe' -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'Cannot install development dependencies.' }
}
Write-Host 'Ready. Run scripts/start-web.ps1 or dotnet run --project desktop/CimcLab.csproj'
