param(
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = '0.4.0',
    [string]$PackageDirectory,
    [string]$OutputDirectory,
    [ValidatePattern('^[A-Za-z0-9-]{1,48}$')][string]$TestId
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PackageDirectory) { $PackageDirectory = Join-Path $projectRoot "artifacts/CIMC-Studio-$Version-win-x64" }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $projectRoot 'artifacts' }
$package = (Resolve-Path -LiteralPath $PackageDirectory).Path
foreach ($required in @('CIMC-Studio.exe','CIMC-Engine.exe','web/index.html','web/assets/schematics/GD32F470-V1.0-schematic.pdf','firmware/demo.hex','THIRD_PARTY_NOTICES.md')) {
    if (-not (Test-Path -LiteralPath (Join-Path $package $required))) { throw "Release is incomplete: $required" }
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$destination = (Resolve-Path -LiteralPath $OutputDirectory).Path
$compiler = & "$PSScriptRoot/setup-inno.ps1"
$arguments = @('/Qp',"/DAppVersion=$Version","/DPackageDir=$package","/DOutputDir=$destination",("/DIconFile=" + (Join-Path $projectRoot 'assets/app.ico')))
if ($TestId) { $arguments += "/DTestId=$TestId" }
$arguments += Join-Path $projectRoot 'packaging/windows/cimc-studio.iss'
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw 'Windows installer compilation failed.' }
$name = if ($TestId) { "CIMC-Studio-$Version-Test-$TestId-Setup-x64.exe" } else { "CIMC-Studio-$Version-Setup-x64.exe" }
$result = Join-Path $destination $name
if (-not (Test-Path -LiteralPath $result)) { throw 'Compiler did not produce the expected installer.' }
Write-Output $result
