param(
    [Parameter(Mandatory=$true)][string]$Bundle,
    [Parameter(Mandatory=$true)][string]$NsisPath,
    [string]$OutputRoot = 'dist/setup',
    [switch]$TestIdentity,
    [string]$SigningConfig,
    [switch]$AllowUnsigned
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'code-signing.ps1')
$signing = Get-CodeSigningSettings -SigningConfig $SigningConfig -AllowUnsigned:$AllowUnsigned
$projectRoot = Split-Path $PSScriptRoot -Parent
$bundlePath = (Resolve-Path -LiteralPath $Bundle).Path
$compiler = (Resolve-Path -LiteralPath (Join-Path $NsisPath 'makensis.exe')).Path
$distRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'dist'))
$outputPath = [IO.Path]::GetFullPath($(if ([IO.Path]::IsPathRooted($OutputRoot)) { $OutputRoot } else { Join-Path $projectRoot $OutputRoot }))
if ($outputPath -ne $distRoot -and -not $outputPath.StartsWith($distRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Setup output must be under dist' }
foreach ($path in @($bundlePath, $outputPath)) {
    for ($part = $path; $part; $part = Split-Path $part -Parent) {
        if ((Get-Item -LiteralPath $part -ErrorAction SilentlyContinue).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked build paths are not supported' }
    }
}
$manifest = Get-Content -LiteralPath (Join-Path $bundlePath '.bongo-cat-chat-install') -Raw | ConvertFrom-Json
$version = $manifest.active
if ($manifest.schema -ne 2 -or $version -notmatch '^(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?$') { throw 'Invalid bundle version' }
$numericVersion = "$($Matches[1]).$($Matches[2]).$($Matches[3]).$(if ($Matches[4]) { $Matches[4] } else { '0' })"
foreach ($name in @('install.ps1', 'uninstall.ps1')) {
    if ((Get-FileHash -LiteralPath (Join-Path $bundlePath $name)).Hash -ne (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $name)).Hash) { throw "Rebuild bundle: $name is stale" }
}
if ($signing) { Invoke-BundleSigning -Settings $signing -Bundle $bundlePath -VerifyOnly }
$installedKb = [math]::Ceiling((Get-ChildItem -LiteralPath $bundlePath -Recurse -File -Force | Measure-Object Length -Sum).Sum / 1024)
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
$suffix = if ($TestIdentity) { '-test' } else { '' }
$outputFile = Join-Path $outputPath "BongoCatChat-$version-windows-x64-Setup$suffix.exe"
if ((Test-Path -LiteralPath $outputFile) -or (Test-Path -LiteralPath ($outputFile + '.sha256'))) { throw 'Setup assets already exist; use a fresh output directory' }
$pendingFile = Join-Path $outputPath ('.setup-' + [Guid]::NewGuid().ToString('N') + '.exe')
$compilerArgs = @('/V2', '/NOCD', "/DBUNDLE_DIR=$bundlePath", "/DOUTPUT_FILE=$pendingFile", "/DAPP_VERSION=$version", "/DNUMERIC_VERSION=$numericVersion", "/DINSTALLED_KB=$installedKb", "/DREMOVAL_SCRIPT=$(Join-Path $PSScriptRoot 'uninstall.ps1')")
if ($TestIdentity) { $compilerArgs += @('/DAPP_ID=BongoCatChatInstallerTest', '/DAPP_NAME=Bongo Cat Chat Installer Test') }
$originalSigningConfig = $env:BONGO_CODE_SIGNING_CONFIG
if ($signing) { $resolvedSigningConfig = (Resolve-Path -LiteralPath $SigningConfig).Path }
Push-Location $projectRoot
try {
    if ($signing) {
        $env:BONGO_CODE_SIGNING_CONFIG = $resolvedSigningConfig
        $compilerArgs += '/DSIGNING_ENABLED'
    }
    & $compiler @compilerArgs (Join-Path $PSScriptRoot 'installer.nsi')
    if ($LASTEXITCODE -ne 0) { throw 'NSIS build or uninstaller signing failed' }
    if ($signing) { Set-WindowsSignature -Settings $signing -Path $pendingFile }
    $hash = (Get-FileHash -LiteralPath $pendingFile -Algorithm SHA256).Hash.ToLowerInvariant()
    Move-Item -LiteralPath $pendingFile -Destination $outputFile
    "$hash  $([IO.Path]::GetFileName($outputFile))" | Set-Content -LiteralPath ($outputFile + '.sha256') -Encoding ascii
    Write-Output $outputFile
} finally {
    $env:BONGO_CODE_SIGNING_CONFIG = $originalSigningConfig
    if (Test-Path -LiteralPath $pendingFile) { Remove-Item -LiteralPath $pendingFile -Force }
    Pop-Location
}
