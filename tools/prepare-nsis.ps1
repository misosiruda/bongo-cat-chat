param([string]$OutputRoot = 'dist/tooling')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$dist = [IO.Path]::GetFullPath((Join-Path $projectRoot 'dist'))
$target = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputRoot))
if (!$target.StartsWith($dist + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Tooling must stay under dist' }
New-Item -ItemType Directory -Force -Path $target | Out-Null
$archive = Join-Path $target 'nsis-3.13.zip'
$expected = 'ba63dffc4410ee89193e1cb5a41989991bd77c61068da17e3156d136b7b0b3d8'
if (!(Test-Path -LiteralPath $archive) -or (Get-FileHash -LiteralPath $archive).Hash -ne $expected) {
    Invoke-WebRequest 'https://downloads.sourceforge.net/project/nsis/NSIS%203/3.13/nsis-3.13.zip' -OutFile $archive
}
if ((Get-FileHash -LiteralPath $archive).Hash -ne $expected) { throw 'NSIS archive checksum mismatch' }
Expand-Archive -LiteralPath $archive -DestinationPath $target -Force
$compilerRoot = Join-Path $target 'nsis-3.13'
if (!(Test-Path -LiteralPath (Join-Path $compilerRoot 'makensis.exe'))) { throw 'NSIS compiler missing' }
Write-Output $compilerRoot
