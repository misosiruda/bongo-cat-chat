# Shared Authenticode policy for local builds. Never imports a key or changes trust stores.
# A Python/NSIS child can inherit PowerShell 7 module paths while running Windows
# PowerShell 5.1. Load this host's built-ins explicitly to avoid cross-version modules.
Import-Module "$PSHOME/Modules/Microsoft.PowerShell.Utility/Microsoft.PowerShell.Utility.psd1" -ErrorAction Stop
Import-Module "$PSHOME/Modules/Microsoft.PowerShell.Security/Microsoft.PowerShell.Security.psd1" -ErrorAction Stop

function Get-CodeSigningSettings {
    param([string]$SigningConfig, [switch]$AllowUnsigned)
    if ($AllowUnsigned) {
        if ($SigningConfig) { throw 'Choose SigningConfig or AllowUnsigned, not both' }
        Write-Warning 'UNSIGNED DEVELOPMENT BUILD: Windows publisher warnings remain.'
        return $null
    }
    if (-not $SigningConfig) { throw 'Windows signing is required. Supply -SigningConfig, or explicitly use -AllowUnsigned for local development.' }
    $configPath = (Resolve-Path -LiteralPath $SigningConfig -ErrorAction Stop).Path
    $settings = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $allowed = @('schema', 'signToolPath', 'certificateThumbprint', 'certificateStoreLocation', 'timestampUrl')
    foreach ($property in $settings.PSObject.Properties.Name) {
        if ($property -notin $allowed) { throw "Unknown Windows signing setting: $property" }
    }
    if ($settings.schema -ne 1) { throw 'Unsupported Windows signing config schema' }
    if ($settings.certificateThumbprint -notmatch '^[0-9a-fA-F]{40}$') { throw 'A specific 40-character certificate thumbprint is required' }
    if ($settings.certificateStoreLocation -notin @('CurrentUser', 'LocalMachine')) { throw 'certificateStoreLocation must be CurrentUser or LocalMachine' }
    $timestamp = $null
    if (-not [Uri]::TryCreate($settings.timestampUrl, [UriKind]::Absolute, [ref]$timestamp) -or $timestamp.Scheme -notin @('http', 'https') -or $timestamp.UserInfo -or $timestamp.Fragment) {
        throw 'A credential-free HTTP(S) RFC 3161 timestamp URL is required'
    }
    if (-not [IO.Path]::IsPathRooted($settings.signToolPath) -or -not (Test-Path -LiteralPath $settings.signToolPath -PathType Leaf)) { throw 'signToolPath must point to an installed Windows SDK SignTool executable' }
    if ([IO.Path]::GetExtension($settings.signToolPath) -ne '.exe') { throw 'signToolPath must be an executable' }
    return $settings
}

function Assert-SigningFile {
    param([Parameter(Mandatory=$true)][string]$Path)
    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) { throw "Signing target missing: $fullPath" }
    for ($part = $fullPath; $part; $part = Split-Path $part -Parent) {
        if ((Get-Item -LiteralPath $part -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked signing paths are not supported' }
    }
    return $fullPath
}

function Invoke-CodeSigningTool {
    param($Settings, [string[]]$Arguments)
    & $Settings.signToolPath @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "SignTool failed or returned a warning (exit $LASTEXITCODE)" }
}

function Assert-WindowsSignature {
    param($Settings, [string]$Path)
    $target = Assert-SigningFile -Path $Path
    $signature = Get-AuthenticodeSignature -LiteralPath $target
    if ($signature.Status -ne 'Valid' -or $signature.SignatureType -ne 'Authenticode') { throw "Missing or invalid embedded Windows signature: $target" }
    if ($signature.SignerCertificate.Thumbprint -ne $Settings.certificateThumbprint) { throw "Unexpected Windows signing certificate: $target" }
    if (-not $signature.TimeStamperCertificate) { throw "Windows signature has no timestamp: $target" }
    # /pa verifies ordinary applications; /all rejects invalid additional signatures;
    # /tw makes a missing timestamp a warning, which is treated as a build failure.
    Invoke-CodeSigningTool -Settings $Settings -Arguments @('verify', '/pa', '/all', '/tw', $target)
}

function Set-WindowsSignature {
    param($Settings, [string]$Path)
    $target = Assert-SigningFile -Path $Path
    $arguments = @('sign', '/fd', 'SHA256', '/tr', $Settings.timestampUrl, '/td', 'SHA256',
        '/s', 'My', '/sha1', $Settings.certificateThumbprint, '/d', 'Bongo Cat Chat')
    if ($Settings.certificateStoreLocation -eq 'LocalMachine') { $arguments += '/sm' }
    Invoke-CodeSigningTool -Settings $Settings -Arguments ($arguments + @($target))
    Assert-WindowsSignature -Settings $Settings -Path $target
}

function Get-BundleSigningTargets {
    param([string]$Bundle)
    $bundlePath = (Resolve-Path -LiteralPath $Bundle -ErrorAction Stop).Path
    $markerPath = Assert-SigningFile -Path (Join-Path $bundlePath '.bongo-cat-chat-install')
    $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
    if ($marker.schema -ne 2 -or $marker.active -notmatch '^\d+\.\d+\.\d+(\.dev\d+)?$') { throw 'Invalid signing bundle version' }
    $app = Join-Path $bundlePath "versions/$($marker.active)/BongoCatChatApp"
    # Only binaries built from this repository; do not replace third-party signatures.
    $targets = @((Join-Path $bundlePath 'BongoCatChat.exe'),
        (Join-Path $app 'BongoCatChatApp.exe'),
        (Join-Path $app '_internal/bongo_chat/compatibility/FeatureProbe.exe'),
        (Join-Path $app '_internal/bongo_chat/compatibility/MemoryScan.exe'))
    # Validate the complete list before modifying any file.
    return @($targets | ForEach-Object { Assert-SigningFile -Path $_ })
}

function Invoke-BundleSigning {
    param($Settings, [string]$Bundle, [switch]$VerifyOnly)
    $targets = Get-BundleSigningTargets -Bundle $Bundle
    foreach ($target in $targets) {
        if ($VerifyOnly) { Assert-WindowsSignature -Settings $Settings -Path $target }
        else { Set-WindowsSignature -Settings $Settings -Path $target }
    }
}
