param(
    [Parameter(Mandatory=$true)][string]$Path,
    [string]$SigningConfig = $env:BONGO_CODE_SIGNING_CONFIG
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'code-signing.ps1')
$settings = Get-CodeSigningSettings -SigningConfig $SigningConfig
Set-WindowsSignature -Settings $settings -Path $Path
