param(
    [Parameter(Mandatory=$true)][string]$Bundle,
    [Parameter(Mandatory=$true)][string]$SigningConfig,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'code-signing.ps1')
$settings = Get-CodeSigningSettings -SigningConfig $SigningConfig
Invoke-BundleSigning -Settings $settings -Bundle $Bundle -VerifyOnly:$VerifyOnly
