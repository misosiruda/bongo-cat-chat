param([string]$Python)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (!$Python) { $Python = Join-Path $projectRoot '.venv/Scripts/python.exe' }
$versionText = Get-Content -LiteralPath (Join-Path $projectRoot 'src/bongo_chat/__init__.py') -Raw
if ($versionText -notmatch '__version__\s*=\s*"([0-9.]+(?:dev[0-9]+)?)"') { throw 'Cannot read app version' }
$version = $Matches[1]
$versionResources = Join-Path $projectRoot 'artifacts/windows-version'
& $Python (Join-Path $PSScriptRoot 'windows_version.py') --version $version --output $versionResources
if ($LASTEXITCODE -ne 0) { throw 'Windows version resource generation failed' }
$output = Join-Path $projectRoot 'artifacts/compatibility'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$archive = Join-Path $output 'mono.cecil.0.11.6.nupkg'
$archiveHash = 'd2a23832aaa948ba9a01acc42b5726e34c5f995958f1b30d45c0e7c70b3a72d5'
$dllHash = 'c41bdb9ffd3c5f6e17d2382c1012d73703e035e3f1100245fdd4e08c8dc6eb5b'
function Hash-File([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}
if (!(Test-Path -LiteralPath $archive)) {
    $client = New-Object Net.WebClient
    try { $client.DownloadFile('https://api.nuget.org/v3-flatcontainer/mono.cecil/0.11.6/mono.cecil.0.11.6.nupkg', $archive) }
    finally { $client.Dispose() }
}
if ((Hash-File $archive) -ne $archiveHash) { throw 'Unexpected Mono.Cecil package' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($archive)
try {
    $entry = $zip.GetEntry('lib/net40/Mono.Cecil.dll')
    if (!$entry -or $entry.Length -gt 1048576) { throw 'Missing Mono.Cecil library' }
    [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $output 'Mono.Cecil.dll'), $true)
} finally { $zip.Dispose() }
if ((Hash-File (Join-Path $output 'Mono.Cecil.dll')) -ne $dllHash) { throw 'Unexpected Mono.Cecil library' }
$compiler = Join-Path $env:SystemRoot 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
& $compiler /nologo /optimize+ /target:exe /out:"$output/FeatureProbe.exe" /reference:"$output/Mono.Cecil.dll" /reference:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'compatibility/FeatureProbe.cs') (Join-Path $versionResources 'FeatureProbe.Version.cs')
if ($LASTEXITCODE -ne 0) { throw 'Compatibility helper build failed' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'compatibility/Mono.Cecil.LICENSE.txt') -Destination $output
Write-Output 'Read-only compatibility helper prepared.'
