param([string]$Destination = $PSScriptRoot, [switch]$NoShortcut, [string]$ShortcutName = 'Bongo Cat Chat')
$ErrorActionPreference = 'Stop'
function Assert-NoLinks([string]$Path, [switch]$Tree) {
    for ($part = $Path; $part; $part = Split-Path $part -Parent) {
        if ((Get-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked installation paths are not supported' }
    }
    if ($Tree -and (Test-Path -LiteralPath $Path -PathType Container)) {
        $directories = New-Object 'System.Collections.Generic.Stack[string]'
        $directories.Push($Path)
        while ($directories.Count) {
            foreach ($entry in Get-ChildItem -LiteralPath $directories.Pop() -Force) {
                if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked bundle members are not supported' }
                if ($entry.PSIsContainer) { $directories.Push($entry.FullName) }
            }
        }
    }
}
$lock = $null; $resultCode = 10
try {
    $target = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
    if ($target.Length -le 3) { throw 'Invalid uninstall directory' }
    if (-not $ShortcutName -or $ShortcutName.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) { throw 'Invalid shortcut name' }
    Assert-NoLinks $target
    $marker = Join-Path $target '.bongo-cat-chat-install'
    Assert-NoLinks $marker
    if ((Get-Item -LiteralPath $marker).Length -gt 4096) { throw 'Invalid installation manifest' }
    $observedMarker = Get-Content -LiteralPath $marker -Raw
    $manifest = $observedMarker | ConvertFrom-Json
    if ($manifest.schema -ne 2 -or $manifest.active -notmatch '^\d+\.\d+\.\d+(\.dev\d+)?$') { throw 'Not a verified installation' }
    if (-not (Test-Path -LiteralPath (Join-Path $target 'BongoCatChat.exe') -PathType Leaf)) { throw 'Executable missing; verify installation manually' }
    # Preflight every owned member before deleting anything; leave unrelated root files intact.
    $members = @('versions','.updates','BongoCatChat.exe','uninstall.ps1','.bongo-cat-chat-install')
    foreach ($name in $members + '.bongo-cat-chat-run.lock') {
        $item = [IO.Path]::GetFullPath((Join-Path $target $name))
        if (-not $item.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid uninstall path' }
        Assert-NoLinks $item -Tree
    }
    $resultCode = 20
    $active = Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase) -and $_.Name -ne 'Uninstall.exe'
    }
    if ($active) { throw 'Close Bongo Cat Chat before uninstalling' }
    $resultCode = 40
    $lock = [IO.File]::Open((Join-Path $target '.bongo-cat-chat-run.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
    $resultCode = 20
    $lock.Lock(0, 1)
    $resultCode = 40
    if ((Get-Content -LiteralPath $marker -Raw) -cne $observedMarker) { throw 'Installation changed during preparation; retry uninstall' }
    foreach ($name in $members) {
        $item = Join-Path $target $name
        if (Test-Path -LiteralPath $item) { Remove-Item -LiteralPath $item -Recurse -Force }
    }
    if (-not $NoShortcut) {
        $shortcutPath = Join-Path $env:APPDATA "Microsoft/Windows/Start Menu/Programs/$ShortcutName.lnk"
        if (Test-Path -LiteralPath $shortcutPath) {
            $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
            if ($shortcut.TargetPath -eq (Join-Path $target 'BongoCatChat.exe')) { Remove-Item -LiteralPath $shortcutPath }
        }
    }
    $resultCode = 0
    Write-Output 'App removed. Chat history and settings are retained.'
} catch { Write-Output $_.Exception.Message }
finally { if ($lock) { $lock.Dispose() } }
if ($resultCode -eq 0) { Remove-Item -LiteralPath (Join-Path $target '.bongo-cat-chat-run.lock') -Force -ErrorAction SilentlyContinue }
exit $resultCode
