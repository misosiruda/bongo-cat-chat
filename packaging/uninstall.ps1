$ErrorActionPreference = 'Stop'
$target = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
$marker = Join-Path $target '.bongo-cat-chat-install'
if (-not (Test-Path -LiteralPath $marker) -or (Get-Content -LiteralPath $marker -Raw).Trim() -ne 'BongoCatChat-0.1.0.dev1') { throw 'Not a verified development installation' }
if (-not (Test-Path -LiteralPath (Join-Path $target 'BongoCatChat.exe'))) { throw 'Executable missing; verify installation manually' }
if ((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked installation directory is not supported' }
$active = Get-Process -Name BongoCatChat -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $target 'BongoCatChat.exe') }
if ($active) { throw 'Close Bongo Cat Chat before uninstalling' }
$shortcutPath = Join-Path $env:APPDATA 'Microsoft/Windows/Start Menu/Programs/Bongo Cat Chat.lnk'
if (Test-Path -LiteralPath $shortcutPath) {
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    if ($shortcut.TargetPath -eq (Join-Path $target 'BongoCatChat.exe')) { Remove-Item -LiteralPath $shortcutPath }
}
# Only known bundle members under this verified installation, never a computed recursive root deletion.
foreach ($name in @('_internal','BongoCatChat.exe','.bongo-cat-chat-install')) {
    $item = [IO.Path]::GetFullPath((Join-Path $target $name))
    if (-not $item.StartsWith($target + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid uninstall path' }
    if ((Get-Item -LiteralPath $item -ErrorAction SilentlyContinue).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked bundle member is not supported' }
    if ($name -eq '_internal' -and (Get-ChildItem -LiteralPath $item -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })) { throw 'Linked dependency directory is not supported' }
    if (Test-Path -LiteralPath $item) { Remove-Item -LiteralPath $item -Recurse -Force }
}
Write-Output 'App removed. uninstall.ps1 and chat data are retained. Delete history inside the app before uninstalling if needed.'
