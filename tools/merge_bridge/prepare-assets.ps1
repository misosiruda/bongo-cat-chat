$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$compatibility = Join-Path $root 'artifacts/compatibility'
$output = Join-Path $root 'artifacts/merge-bridge/shipped'
New-Item -ItemType Directory -Force $output | Out-Null
$cecil = Join-Path $compatibility 'Mono.Cecil.dll'
if (!(Test-Path -LiteralPath $cecil)) { throw 'Run tools/prepare-compatibility.ps1 first' }
$compiler = Join-Path $env:SystemRoot 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
& $compiler /nologo /target:exe "/out:$output/MergePrepare.exe" "/reference:$cecil" (Join-Path $PSScriptRoot 'Prepare.cs') (Join-Path $root 'artifacts/windows-version/MergePrepare.Version.cs')
if ($LASTEXITCODE -ne 0) { throw 'Merge prepare tool compilation failed' }
Copy-Item -LiteralPath $cecil -Destination $output
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Bridge.cs') -Destination $output
$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'local-contract.json') -Raw | ConvertFrom-Json
@{
    schema=3
    files=$contract.files
    source_sha256=(Get-FileHash -LiteralPath (Join-Path $output 'Bridge.cs')).Hash.ToLowerInvariant()
    prepare_sha256=(Get-FileHash -LiteralPath (Join-Path $output 'MergePrepare.exe')).Hash.ToLowerInvariant()
    cecil_sha256=(Get-FileHash -LiteralPath $cecil).Hash.ToLowerInvariant()
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output 'contract.json') -Encoding utf8
Write-Output 'Merge source assets prepared without game binaries.'
