param(
    [Parameter(Mandatory = $true)][string]$CurrentVersion,
    [Parameter(Mandatory = $true)][string]$PublicationReport,
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
if ($CurrentVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'CurrentVersion must be a stable numeric version.' }
$current = [version]$CurrentVersion
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$artifactRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'artifacts'))
$prefix = $artifactRoot + [IO.Path]::DirectorySeparatorChar
$ancestor = $artifactRoot
while ($ancestor) {
    if (((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing linked workspace ancestor: $ancestor"
    }
    $ancestor = Split-Path -Parent $ancestor
}
$proof = Get-Content -LiteralPath $PublicationReport -Raw | ConvertFrom-Json
if ($proof.format -ne 'cimc-remote-installer-cleanup-v1' -or $proof.repository -ne 'Epiphany-Lucky/cimc-simulator' -or
    $proof.currentVersion -ne $CurrentVersion -or $proof.verified -isnot [bool] -or $proof.verified -ne $true -or
    $proof.executed -isnot [bool] -or $proof.executed -ne $true -or
    $null -eq $proof.packageVersions.'cimc-studio-windows' -or $null -eq $proof.packageVersions.'cimc-studio-linux') {
    throw 'A successful publication and remote cleanup report for this version is required.'
}
$targets = [Collections.Generic.List[string]]::new()
function Add-OldTarget([IO.FileSystemInfo]$Item, [string]$Version) {
    if ([version]$Version -ge $current) { return }
    $resolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Item.FullName).Path)
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Outside artifacts: $resolved" }
    $ancestor = $resolved
    while ($ancestor.Length -ge $artifactRoot.Length) {
        if (((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing linked target or parent: $ancestor"
        }
        if ($ancestor.Equals($artifactRoot, [StringComparison]::OrdinalIgnoreCase)) { break }
        $ancestor = Split-Path -Parent $ancestor
    }
    $targets.Add($resolved)
}
foreach ($item in Get-ChildItem -LiteralPath $artifactRoot) {
    if ($item.Name -match '^CIMC-Studio-(\d+\.\d+\.\d+)-(?:win-x64|html-local|linux-x64)(?:\.zip|\.tar\.gz)?$' -or
        $item.Name -match '^CIMC-Studio-(\d+\.\d+\.\d+)-Setup-x64\.exe$' -or
        $item.Name -match '^cimc-studio_(\d+\.\d+\.\d+)_amd64\.deb$') {
        Add-OldTarget $item $Matches[1]
    }
    elseif ($item.PSIsContainer -and ($item.Name -match '^github-linux-v\d+\.\d+$' -or $item.Name -match '^installer-smoke-[0-9a-f]+$')) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
        foreach ($file in Get-ChildItem -LiteralPath $item.FullName -File) {
            if ($file.Name -match '^CIMC-Studio-(\d+\.\d+\.\d+)-(?:linux-x64\.tar\.gz|Test-[0-9a-f]+-Setup-x64\.exe)$' -or
                $file.Name -match '^cimc-studio_(\d+\.\d+\.\d+)_amd64\.deb$') {
                Add-OldTarget $file $Matches[1]
            }
        }
    }
}
# A downloaded CI ZIP has a run ID, not a version. Inspect its complete entry list
# before considering it an obsolete installer archive; never infer from its age.
Add-Type -AssemblyName System.IO.Compression.FileSystem
foreach ($archive in Get-ChildItem -LiteralPath $artifactRoot -File -Filter 'cimc-studio-linux-ci-*.zip') {
    $zip = [IO.Compression.ZipFile]::OpenRead($archive.FullName)
    try {
        $versions = @()
        $recognized = $zip.Entries.Count -gt 0
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -match '^CIMC-Studio-(\d+\.\d+\.\d+)-linux-x64\.tar\.gz$' -or
                $entry.FullName -match '^cimc-studio_(\d+\.\d+\.\d+)_amd64\.deb$') { $versions += $Matches[1] }
            else { $recognized = $false }
        }
        if ($recognized -and @($versions | Where-Object { [version]$_ -ge $current }).Count -eq 0) {
            Add-OldTarget $archive $versions[0]
        }
    } finally { $zip.Dispose() }
}
# Validate every recursive target and running executable before deleting anything.
$processes = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath })
foreach ($target in $targets) {
    $item = Get-Item -LiteralPath $target
    if ($item.PSIsContainer) {
        $links = @(Get-ChildItem -LiteralPath $target -Force -Recurse | Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 })
        if ($links.Count) { throw "Refusing recursive cleanup with links: $target" }
    }
    foreach ($process in $processes) {
        $exe = [IO.Path]::GetFullPath($process.ExecutablePath)
        if ($exe.Equals($target, [StringComparison]::OrdinalIgnoreCase) -or $exe.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "An application is still using $target; nothing deleted."
        }
    }
}
$report = [ordered]@{ currentVersion = $CurrentVersion; executed = [bool]$Execute; targets = @($targets); deleted = @(); verified = $false }
try {
    $targets | ForEach-Object { Write-Host $_ }
    if ($Execute) {
        foreach ($target in $targets) {
            # Targets above are resolved absolute paths inside this project's artifacts.
            Remove-Item -LiteralPath $target -Recurse -Force
            $report.deleted += $target
        }
        foreach ($target in $targets) { if (Test-Path -LiteralPath $target) { throw "Old installer still exists: $target" } }
        $report.verified = $true
    }
} finally {
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $artifactRoot "local-cleanup-$CurrentVersion.json") -Encoding UTF8
}
Write-Host $(if ($Execute) { 'Old local installers removed and verified.' } else { 'Dry run; nothing deleted.' })
