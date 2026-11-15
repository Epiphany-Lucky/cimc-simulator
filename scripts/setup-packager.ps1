$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
# Unicorn uses longjmp; the stock CFG-enabled PyInstaller bootloader is incompatible.
# Rebuild only this project's packager, following upstream documentation.
# https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#windows-executables-and-control-flow-guard-cfg
$oldCompile = $env:PYINSTALLER_COMPILE_BOOTLOADER
$oldArgs = $env:PYINSTALLER_BOOTLOADER_WAF_ARGS
try {
    $env:PYINSTALLER_COMPILE_BOOTLOADER = '1'
    $env:PYINSTALLER_BOOTLOADER_WAF_ARGS = '--no-cfg'
    & '.venv/Scripts/python.exe' -m pip install --force-reinstall --no-deps --no-binary=pyinstaller --no-cache-dir pyinstaller==6.22.3
    if ($LASTEXITCODE -ne 0) { throw 'Custom bootloader build failed. Install Visual Studio C++ build tools.' }
} finally {
    $env:PYINSTALLER_COMPILE_BOOTLOADER = $oldCompile
    $env:PYINSTALLER_BOOTLOADER_WAF_ARGS = $oldArgs
}
