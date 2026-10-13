param([string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs/BongoCatChat'), [switch]$NoShortcut)
$ErrorActionPreference = 'Stop'
$source = [IO.Path]::GetFullPath($PSScriptRoot)
$destinationPath = [IO.Path]::GetFullPath($Destination)
if ($source -eq $destinationPath) { throw 'Source and destination must differ' }
if (-not (Test-Path -LiteralPath (Join-Path $source 'BongoCatChat.exe'))) { throw 'Run from the built bundle' }
if (Test-Path -LiteralPath $destinationPath) { throw 'Destination exists; uninstall the previous development build first' }
New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $source 'BongoCatChat.exe') -Destination $destinationPath
Copy-Item -LiteralPath (Join-Path $source '_internal') -Destination $destinationPath -Recurse
Copy-Item -LiteralPath (Join-Path $source 'uninstall.ps1') -Destination $destinationPath
Set-Content -LiteralPath (Join-Path $destinationPath '.bongo-cat-chat-install') -Value 'BongoCatChat-0.1.0.dev1' -Encoding utf8
if (-not $NoShortcut) {
    $shortcutPath = Join-Path $env:APPDATA 'Microsoft/Windows/Start Menu/Programs/Bongo Cat Chat.lnk'
    if (Test-Path -LiteralPath $shortcutPath) { throw 'Shortcut already exists; installation files were copied, shortcut preserved' }
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $destinationPath 'BongoCatChat.exe'
    $shortcut.WorkingDirectory = $destinationPath
    $shortcut.Save()
}
Write-Output 'Development app installed for the current Windows user. Chat data: %LOCALAPPDATA%/BongoCatChat (30 days).'
