$ErrorActionPreference = 'Stop'
$target = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
$marker = Join-Path $target '.bongo-cat-chat-install'
if (-not (Test-Path -LiteralPath $marker)) { throw 'Not a verified development installation' }
$manifest = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
if ($manifest.schema -ne 2 -or $manifest.active -notmatch '^\d+\.\d+\.\d+(\.dev\d+)?$') { throw 'Not a verified versioned installation' }
if (-not (Test-Path -LiteralPath (Join-Path $target 'BongoCatChat.exe'))) { throw 'Executable missing; verify installation manually' }
if ((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked installation directory is not supported' }
for ($part = Split-Path $target -Parent; $part; $part = Split-Path $part -Parent) {
    if ((Get-Item -LiteralPath $part).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked installation path is not supported' }
}
$active = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($target + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) }
if ($active) { throw 'Close Bongo Cat Chat before uninstalling' }
$shortcutPath = Join-Path $env:APPDATA 'Microsoft/Windows/Start Menu/Programs/Bongo Cat Chat.lnk'
if (Test-Path -LiteralPath $shortcutPath) {
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    if ($shortcut.TargetPath -eq (Join-Path $target 'BongoCatChat.exe')) { Remove-Item -LiteralPath $shortcutPath }
}
# Only known bundle members under this verified installation, never a computed recursive root deletion.
foreach ($name in @('versions','.updates','BongoCatChat.exe','.bongo-cat-chat-install','.bongo-cat-chat-run.lock')) {
    $item = [IO.Path]::GetFullPath((Join-Path $target $name))
    if (-not $item.StartsWith($target + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid uninstall path' }
    if ((Get-Item -LiteralPath $item -ErrorAction SilentlyContinue).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked bundle member is not supported' }
    if ((Test-Path -LiteralPath $item -PathType Container) -and (Get-ChildItem -LiteralPath $item -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })) { throw 'Linked dependency directory is not supported' }
    if (Test-Path -LiteralPath $item) { Remove-Item -LiteralPath $item -Recurse -Force }
}
Write-Output 'App removed. uninstall.ps1 and chat data are retained. Delete history inside the app before uninstalling if needed.'
