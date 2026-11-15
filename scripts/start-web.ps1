param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run scripts/setup.ps1 first.' }
Write-Host "Open http://127.0.0.1:$Port in your browser. Ctrl+C stops the engine."
& '.venv/Scripts/python.exe' engine/server.py --port $Port --web-root web
