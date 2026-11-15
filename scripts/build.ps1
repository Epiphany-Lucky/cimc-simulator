param([string]$Version = '0.1.0')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run scripts/setup.ps1 -Testing first.' }
& '.venv/Scripts/python.exe' -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Engine tests failed; packaging stopped.' }
& '.venv/Scripts/python.exe' -c "import pathlib,PyInstaller,pefile,sys; p=pathlib.Path(PyInstaller.__file__).parent/'bootloader/Windows-64bit-intel/run.exe'; sys.exit(1 if pefile.PE(str(p)).OPTIONAL_HEADER.DllCharacteristics & 0x4000 else 0)"
if ($LASTEXITCODE -ne 0) { & "$PSScriptRoot/setup-packager.ps1" }
& '.venv/Scripts/python.exe' -m PyInstaller --clean --noconfirm --onefile --name CIMC-Engine --collect-all unicorn --distpath artifacts/engine --workpath artifacts/pyinstaller --specpath artifacts engine/server.py
if ($LASTEXITCODE -ne 0) { throw 'Engine packaging failed.' }
$releaseRoot = Join-Path $projectRoot "artifacts/CIMC-Studio-$Version-win-x64"
dotnet publish desktop/CimcLab.csproj -c Release -r win-x64 --self-contained true -o $releaseRoot -p:Version=$Version
if ($LASTEXITCODE -ne 0) { throw 'Desktop publishing failed.' }
Copy-Item -LiteralPath 'artifacts/engine/CIMC-Engine.exe' -Destination $releaseRoot -Force
Copy-Item -LiteralPath 'web' -Destination $releaseRoot -Recurse -Force
Copy-Item -LiteralPath 'firmware' -Destination $releaseRoot -Recurse -Force
Copy-Item -LiteralPath 'docs' -Destination $releaseRoot -Recurse -Force
Copy-Item -LiteralPath 'licenses' -Destination $releaseRoot -Recurse -Force
Copy-Item -LiteralPath 'README.md','THIRD_PARTY_NOTICES.md','CHANGELOG.md' -Destination $releaseRoot -Force
if (-not (Test-Path -LiteralPath 'artifacts/third-party-source/unicorn-2.1.4.tar.gz')) {
    New-Item -ItemType Directory -Path 'artifacts/third-party-source' -Force | Out-Null
    Invoke-WebRequest -Uri 'https://github.com/unicorn-engine/unicorn/archive/refs/tags/2.1.4.tar.gz' -OutFile 'artifacts/third-party-source/unicorn-2.1.4.tar.gz'
}
Copy-Item -LiteralPath 'artifacts/third-party-source' -Destination $releaseRoot -Recurse -Force
$sourceRoot = Join-Path $releaseRoot 'source'
foreach ($folder in @('engine','tests','scripts','desktop')) {
    $destination = Join-Path $sourceRoot $folder
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Get-ChildItem -LiteralPath $folder -File | Copy-Item -Destination $destination -Force
}
Set-Content -LiteralPath (Join-Path $releaseRoot 'Open-Web.cmd') -Encoding ascii -Value '@echo off', 'start "" "%~dp0CIMC-Studio.exe" --web'
$htmlRoot = Join-Path $projectRoot "artifacts/CIMC-Studio-$Version-html-local"
New-Item -ItemType Directory -Path $htmlRoot -Force | Out-Null
Copy-Item -LiteralPath 'artifacts/engine/CIMC-Engine.exe' -Destination $htmlRoot -Force
foreach ($folder in @('web','firmware','docs','licenses','source','third-party-source')) {
    Copy-Item -LiteralPath (Join-Path $releaseRoot $folder) -Destination $htmlRoot -Recurse -Force
}
Copy-Item -LiteralPath 'README.md','THIRD_PARTY_NOTICES.md','CHANGELOG.md' -Destination $htmlRoot -Force
Set-Content -LiteralPath (Join-Path $htmlRoot 'Open-Web.cmd') -Encoding ascii -Value '@echo off', '"%~dp0CIMC-Engine.exe" --port 0 --open-browser', 'pause'
$htmlZip = Join-Path $projectRoot "artifacts/CIMC-Studio-$Version-html-local.zip"
Compress-Archive -LiteralPath $htmlRoot -DestinationPath $htmlZip -Force
$zipPath = Join-Path $projectRoot "artifacts/CIMC-Studio-$Version-win-x64.zip"
Compress-Archive -LiteralPath $releaseRoot -DestinationPath $zipPath -Force
Write-Host "Release: $zipPath"
Write-Host "HTML: $htmlZip"
