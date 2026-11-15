$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $projectRoot 'artifacts/tools/inno-6.7.4'
$compiler = Join-Path $toolRoot 'ISCC.exe'
function Ensure-ChineseTranslation {
    # Official translation listed at jrsoftware.org/inno-setup/translations.
    # The 6.7.4 installer predates bundling it in Languages; pin the compatible 6.5+ file.
    $language = Join-Path $toolRoot 'Languages/ChineseSimplified.isl'
    $languageHash = 'e0b0b350e2245f3c5e65586dfe43d574f6e7f06f2261149aba284954b3fc9a8d'
    if (-not (Test-Path -LiteralPath $language)) {
        Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/jrsoftware/issrc/6ef32198ef1f7b7b375cd4b6b90896c2a58eb4c2/Files/Languages/ChineseSimplified.isl' -OutFile $language
    }
    if ((Get-FileHash -LiteralPath $language -Algorithm SHA256).Hash.ToLowerInvariant() -ne $languageHash) {
        throw 'The pinned official Simplified Chinese translation has an unexpected SHA-256.'
    }
}
if (Test-Path -LiteralPath $compiler) {
    Ensure-ChineseTranslation
    Write-Output $compiler
    return
}
$downloadRoot = Join-Path $projectRoot 'artifacts/tools/downloads'
New-Item -ItemType Directory -Path $downloadRoot -Force | Out-Null
$installer = Join-Path $downloadRoot 'innosetup-6.7.4.exe'
$expectedHash = 'a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c'
$uri = 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe'
if (-not (Test-Path -LiteralPath $installer)) {
    try {
        Invoke-WebRequest -Uri $uri -OutFile $installer
    } catch {
        if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw }
        & gh release download is-6_7_4 --repo jrsoftware/issrc --pattern innosetup-6.7.4.exe --dir $downloadRoot --clobber
        if ($LASTEXITCODE -ne 0) { throw 'Cannot download the pinned Inno Setup compiler.' }
    }
}
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
    throw 'Inno Setup SHA-256 does not match the official immutable release.'
}
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'CN=Pyrsys B\.V\.') {
    throw "Inno Setup publisher signature validation failed: $($signature.Status)."
}
$arguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/CURRENTUSER','/NOICONS','/TASKS=',('/DIR="{0}"' -f $toolRoot))
$process = Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $compiler)) {
    throw "Inno Setup tool installation failed: $($process.ExitCode)."
}
Ensure-ChineseTranslation
Write-Output $compiler
