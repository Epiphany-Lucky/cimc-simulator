param([switch]$Gnu, [ValidateSet('demo','systick','adc_probe','spiflash_probe')][string]$Target='demo')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $keilBin = 'D:\keil\Keil_V5\ARM\ARMCLANG\bin'
    if (-not $Gnu -and (Test-Path -LiteralPath "$keilBin\armclang.exe")) {
        & "$keilBin\armclang.exe" --target=arm-arm-none-eabi -mcpu=cortex-m4 -mthumb -O1 -ffreestanding -fno-builtin -c "$Target.c" -o "$Target.o"
        if ($LASTEXITCODE) { throw 'Keil compilation failed' }
        & "$keilBin\armlink.exe" --scatter=keil.sct --entry=Reset_Handler --no_scanlib "$Target.o" "--output=$Target.axf" --map "--list=$Target.map"
        if ($LASTEXITCODE) { throw 'Keil link failed' }
        & "$keilBin\fromelf.exe" --bin "--output=$Target.bin" "$Target.axf"
        if ($LASTEXITCODE) { throw 'Keil BIN export failed' }
        & "$keilBin\fromelf.exe" --i32 "--output=$Target.hex" "$Target.axf"
        if ($LASTEXITCODE) { throw 'Keil HEX export failed' }
        'Keil Arm Compiler 6 (armclang/armlink/fromelf)' | Set-Content -LiteralPath compiler.txt -Encoding utf8
    } else {
        arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb -O1 -ffreestanding -fno-builtin -nostdlib '-Wl,-T,linker.ld' "-Wl,-Map,$Target.map" -o "$Target.elf" "$Target.c"
        if ($LASTEXITCODE) { throw 'GNU firmware build failed' }
        arm-none-eabi-objcopy -O binary "$Target.elf" "$Target.bin"
        arm-none-eabi-objcopy -O ihex "$Target.elf" "$Target.hex"
        'GNU Arm Embedded GCC' | Set-Content -LiteralPath compiler.txt -Encoding utf8
    }
} finally { Pop-Location }
