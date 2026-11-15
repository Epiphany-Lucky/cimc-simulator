param([string]$Version = '0.1.0')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run scripts/setup.ps1 -Testing first.' }
& '.venv/Scripts/python.exe' -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Engine tests failed; packaging stopped.' }
& '.venv/Scripts/python.exe' -m PyInstaller --noconfirm --onefile --name CIMC-Engine --collect-all unicorn --distpath artifacts/engine --workpath artifacts/pyinstaller --specpath artifacts engine/server.py
if ($LASTEXITCODE -ne 0) { throw 'Engine packaging failed.' }
$releaseRoot = Join-Path $projectRoot "artifacts/CIMC-Studio-$Version-win-x64"
dotnet publish desktop/CimcLab.csproj -c Release -r win-x64 --self-contained true -o $releaseRoot -p:Version=$Version
if ($LASTEXITCODE -ne 0) { throw 'Desktop publishing failed.' }
Copy-Item -LiteralPath 'artifacts/engine/CIMC-Engine.exe' -Destination $releaseRoot -Force
Copy-Item -LiteralPath 'web' -Destination $releaseRoot -Recurse -Force
Copy-Item -LiteralPath 'firmware' -Destination $releaseRoot -Recurse -Force
Copy-Item -LiteralPath 'docs' -Destination $releaseRoot -Recurse -Force
Copy-Item -LiteralPath 'README.md','THIRD_PARTY_NOTICES.md','CHANGELOG.md' -Destination $releaseRoot -Force
Set-Content -LiteralPath (Join-Path $releaseRoot 'Open-Web.cmd') -Encoding ascii -Value '@echo off', 'start "" "%~dp0CIMC-Studio.exe" --web'
$zipPath = Join-Path $projectRoot "artifacts/CIMC-Studio-$Version-win-x64.zip"
Compress-Archive -LiteralPath $releaseRoot -DestinationPath $zipPath -Force
Write-Host "Release: $zipPath"
