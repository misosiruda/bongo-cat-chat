param([string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs/BongoCatChat'), [switch]$NoShortcut)
$ErrorActionPreference = 'Stop'
$source = [IO.Path]::GetFullPath($PSScriptRoot)
$destinationPath = [IO.Path]::GetFullPath($Destination)
if ($source -eq $destinationPath) { throw 'Source and destination must differ' }
if ($destinationPath.StartsWith($source + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Destination must be outside the source bundle' }
if (-not (Test-Path -LiteralPath (Join-Path $source 'BongoCatChat.exe'))) { throw 'Run from the built bundle' }
if (Test-Path -LiteralPath $destinationPath) { throw 'Destination exists; uninstall the previous development build first' }
foreach ($path in @($source, $destinationPath)) {
    for ($part = $path; $part; $part = Split-Path $part -Parent) {
        if ((Get-Item -LiteralPath $part -ErrorAction SilentlyContinue).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked installation paths are not supported' }
    }
}
$marker = Get-Content -LiteralPath (Join-Path $source '.bongo-cat-chat-install') -Raw | ConvertFrom-Json
if ($marker.schema -ne 2 -or $marker.active -notmatch '^\d+\.\d+\.\d+(\.dev\d+)?$') { throw 'Invalid version manifest' }
$sourceVersion = Join-Path $source "versions/$($marker.active)"
if (-not (Test-Path -LiteralPath (Join-Path $sourceVersion 'BongoCatChatApp/BongoCatChatApp.exe'))) { throw 'Version executable missing' }
if (Get-ChildItem -LiteralPath $sourceVersion -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Linked version files are not supported' }
New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $source 'BongoCatChat.exe') -Destination $destinationPath
New-Item -ItemType Directory -Path (Join-Path $destinationPath 'versions') | Out-Null
Copy-Item -LiteralPath $sourceVersion -Destination (Join-Path $destinationPath 'versions') -Recurse
Copy-Item -LiteralPath (Join-Path $source 'uninstall.ps1') -Destination $destinationPath
@{schema=2;active=$marker.active;previous=$null} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $destinationPath '.bongo-cat-chat-install') -Encoding utf8
if (-not $NoShortcut) {
    $shortcutPath = Join-Path $env:APPDATA 'Microsoft/Windows/Start Menu/Programs/Bongo Cat Chat.lnk'
    if (Test-Path -LiteralPath $shortcutPath) { throw 'Shortcut already exists; installation files were copied, shortcut preserved' }
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $destinationPath 'BongoCatChat.exe'
    $shortcut.WorkingDirectory = $destinationPath
    $shortcut.Save()
}
Write-Output 'Development app installed for the current Windows user. Chat data: %LOCALAPPDATA%/BongoCatChat (30 days).'
