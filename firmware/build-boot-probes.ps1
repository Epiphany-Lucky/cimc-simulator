param([string]$KeilBin = 'D:\keil\Keil_V5\ARM\ARMCLANG\bin')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $compilerPath = Join-Path $KeilBin 'armclang.exe'
    $linkerPath = Join-Path $KeilBin 'armlink.exe'
    $exporterPath = Join-Path $KeilBin 'fromelf.exe'
    foreach ($toolPath in @($compilerPath, $linkerPath, $exporterPath)) {
        if (-not (Test-Path -LiteralPath $toolPath -PathType Leaf)) {
            throw "Required Keil tool was not found: $toolPath"
        }
    }

    $compilerVersion = (& $compilerPath --version | Out-String).Trim()
    if ($LASTEXITCODE) { throw 'Cannot read Keil compiler version' }
    $linkerVersion = (& $linkerPath --vsn | Out-String).Trim()
    if ($LASTEXITCODE) { throw 'Cannot read Keil linker version' }
    $exporterVersion = (& $exporterPath --vsn | Out-String).Trim()
    if ($LASTEXITCODE) { throw 'Cannot read Keil exporter version' }

    $targets = @(
        @{ Name = 'bootloader_probe'; Source = 'boot_probe.c'; AppId = 0; Base = [uint32]0x08000000; InitialMsp = [uint32]0x20010000 },
        @{ Name = 'app_a_probe'; Source = 'app_probe.c'; AppId = 1; Base = [uint32]0x08010000; InitialMsp = [uint32]0x20018000 },
        @{ Name = 'app_b_probe'; Source = 'app_probe.c'; AppId = 2; Base = [uint32]0x08020000; InitialMsp = [uint32]0x20020000 }
    )
    $manifestTargets = @()
    foreach ($target in $targets) {
        $targetName = $target.Name
        $compileArgs = @('--target=arm-arm-none-eabi', '-mcpu=cortex-m4', '-mthumb', '-O1',
            '-ffreestanding', '-fno-builtin', '-Wall', '-Wextra', '-Werror', '-c', $target.Source,
            '-o', "$targetName.o")
        if ($target.AppId) { $compileArgs += "-DAPP_ID=$($target.AppId)" }
        & $compilerPath @compileArgs
        if ($LASTEXITCODE) { throw "Keil compilation failed: $targetName" }
        & $linkerPath "--scatter=$targetName.sct" --entry=Reset_Handler --no_scanlib "$targetName.o" "--output=$targetName.axf" --map "--list=$targetName.map"
        if ($LASTEXITCODE) { throw "Keil link failed: $targetName" }
        & $exporterPath --bin "--output=$targetName.bin" "$targetName.axf"
        if ($LASTEXITCODE) { throw "Keil BIN export failed: $targetName" }
        & $exporterPath --i32 "--output=$targetName.hex" "$targetName.axf"
        if ($LASTEXITCODE) { throw "Keil HEX export failed: $targetName" }

        $binary = [System.IO.File]::ReadAllBytes((Join-Path $PSScriptRoot "$targetName.bin"))
        $initialMsp = [BitConverter]::ToUInt32($binary, 0)
        $entry = [BitConverter]::ToUInt32($binary, 4)
        $entryAddress = $entry -band [uint32]4294967294
        if ($initialMsp -ne $target.InitialMsp -or -not ($entry -band 1) -or
            $entryAddress -lt $target.Base -or
            $entryAddress -ge ($target.Base + $binary.Length)) {
            throw "Generated vector table failed validation: $targetName"
        }
        $hashes = [ordered]@{}
        foreach ($file in @($target.Source, "$targetName.sct", "$targetName.hex", "$targetName.bin", "$targetName.axf", "$targetName.map")) {
            $hashes[$file] = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $manifestTargets += [ordered]@{
            name = $targetName
            source = $target.Source
            appId = $target.AppId
            address = ('0x{0:X8}' -f $target.Base)
            initialMsp = ('0x{0:X8}' -f $initialMsp)
            entry = ('0x{0:X8}' -f $entry)
            size = $binary.Length
            sha256 = $hashes
        }
        Write-Output ("Built {0}: {1} bytes at 0x{2:X8}" -f $targetName, $binary.Length, $target.Base)
    }
    $manifest = [ordered]@{
        format = 'cimc-boot-probe-build'
        version = 1
        generatedAtUtc = [DateTime]::UtcNow.ToString('o')
        compiler = $compilerVersion
        linker = $linkerVersion
        exporter = $exporterVersion
        buildScriptSha256 = (Get-FileHash -LiteralPath 'build-boot-probes.ps1' -Algorithm SHA256).Hash.ToLowerInvariant()
        targets = $manifestTargets
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath 'boot-probes-manifest.json' -Encoding utf8
} finally {
    Pop-Location
}
