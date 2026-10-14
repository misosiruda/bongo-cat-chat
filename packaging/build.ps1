param([string]$OutputRoot = 'dist')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$distRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'dist'))
$outputPath = [IO.Path]::GetFullPath($(if ([IO.Path]::IsPathRooted($OutputRoot)) { $OutputRoot } else { Join-Path $projectRoot $OutputRoot }))
if ($outputPath -ne $distRoot -and -not $outputPath.StartsWith($distRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Build output must stay under the project dist directory' }
$bundle = Join-Path $outputPath 'BongoCatChat'
for ($candidate = $bundle; $candidate -and $candidate -ne $projectRoot; $candidate = Split-Path $candidate -Parent) {
    if ((Get-Item -LiteralPath $candidate -ErrorAction SilentlyContinue).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked build output is not supported' }
}
$active = Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($bundle + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}
if ($active) { throw 'This output bundle is running. Close it yourself or choose another -OutputRoot under dist.' }
$originalPath = $env:PATH
# Do not resolve native imports from unrelated tools (for example Poppler's ICU).
$env:PATH = (Join-Path $env:SystemRoot 'System32') + ';' + $env:SystemRoot + ';' + (Split-Path $python)
Push-Location $projectRoot
try {
    & (Join-Path $projectRoot 'tools/prepare-compatibility.ps1')
    $version = (& $python -c "import sys; sys.path.insert(0, 'src'); from bongo_chat import __version__; print(__version__)").Trim()
    if ($version -notmatch '^\d+\.\d+\.\d+(\.dev\d+)?$') { throw 'Invalid app version' }
    $versionPath = Join-Path $bundle "versions/$version"
    & $python -m PyInstaller --clean --noconfirm --windowed --onedir --distpath $versionPath --name BongoCatChatApp --paths src --collect-data bongo_chat --collect-data UnityPy --collect-data archspec --collect-binaries fmod_toolkit --copy-metadata UnityPy --add-data 'artifacts/compatibility/FeatureProbe.exe;bongo_chat/compatibility' --add-data 'artifacts/compatibility/MemoryScan.exe;bongo_chat/compatibility' --add-data 'artifacts/compatibility/Mono.Cecil.dll;bongo_chat/compatibility' --add-data 'tools/compatibility/Mono.Cecil.LICENSE.txt;bongo_chat/compatibility' tools/launch.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
    & $python -m PyInstaller --clean --noconfirm --windowed --onefile --distpath $bundle --name BongoCatChat --paths src --add-data 'src/bongo_chat/update-config.json;bongo_chat' tools/launch_bootstrap.py
    if ($LASTEXITCODE -ne 0) { throw 'Launcher build failed' }
    $forbidden = Get-ChildItem -LiteralPath $bundle -Recurse -File | Where-Object { $_.Name -in @('steam_api64.dll','Assembly-CSharp.dll','mono-2.0-bdwgc.dll','sharedassets0.assets','resources.assets','Heathen.Steamworks.dll') }
    if ($forbidden) { throw 'Bundle unexpectedly contains game files' }
    if (Get-ChildItem -LiteralPath $bundle -Recurse -File -Filter 'icu*.dll') { throw 'Unexpected bundled ICU: this Qt build uses the Windows ICU API' }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install.ps1') -Destination $bundle
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'uninstall.ps1') -Destination $bundle
    @{schema=2;active=$version;previous=$null} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $bundle '.bongo-cat-chat-install') -Encoding utf8
    @{schema=1;version=$version} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $versionPath '.bongo-version.json') -Encoding utf8
    Write-Output 'Local development bundle created. Public distribution is not approved.'
} finally {
    $env:PATH = $originalPath
    Pop-Location
}
