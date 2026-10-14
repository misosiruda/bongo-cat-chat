param([string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs/BongoCatChat'), [switch]$NoShortcut, [string]$ShortcutName = 'Bongo Cat Chat')
$ErrorActionPreference = 'Stop'
# Keep both engines standalone for existing installation/update formats.
# IShellLinkW avoids WSH TargetPath parsing through the machine's ANSI code page.
function Initialize-ShortcutInterop {
    if ('BongoChatShortcut' -as [type]) { return }
    Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
public static class BongoChatShortcut {
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    private class ShellLink {}
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface ILink {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int size, IntPtr data, uint flags);
        void GetIDList(out IntPtr list);
        void SetIDList(IntPtr list);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int size);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int size);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int size);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetHotkey(out short value);
        void SetHotkey(short value);
        void GetShowCmd(out int value);
        void SetShowCmd(int value);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int size, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string value, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string value, uint reserved);
        void Resolve(IntPtr window, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string value);
    }
    public static string Read(string path) {
        object link = new ShellLink();
        try {
            ((IPersistFile)link).Load(path, 0);
            var value = new StringBuilder(32768);
            ((ILink)link).GetPath(value, value.Capacity, IntPtr.Zero, 4);
            return value.ToString();
        } finally { Marshal.FinalReleaseComObject(link); }
    }
    public static void Write(string path, string target, string directory) {
        object link = new ShellLink();
        try {
            ((ILink)link).SetPath(target);
            ((ILink)link).SetWorkingDirectory(directory);
            ((IPersistFile)link).Save(path, true);
        } finally { Marshal.FinalReleaseComObject(link); }
    }
}
"@
}
# Also used by Setup.exe. No network, elevation, game access, or user-data writes.
function Assert-NoLinks([string]$Path, [switch]$Tree) {
    for ($part = $Path; $part; $part = Split-Path $part -Parent) {
        if ((Get-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked paths are not supported' }
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
function Get-Manifest([string]$Path) {
    if ((Get-Item -LiteralPath $Path).Length -gt 4096) { throw 'Invalid installation manifest' }
    $value = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($value.schema -ne 2 -or $value.active -notmatch '^\d+\.\d+\.\d+(\.dev\d+)?$') { throw 'Invalid installation manifest' }
    if ($value.previous -and $value.previous -notmatch '^\d+\.\d+\.\d+(\.dev\d+)?$') { throw 'Invalid previous version' }
    return $value
}
function Compare-AppVersion([string]$Left, [string]$Right) {
    $a = $Left -split '\.dev'; $b = $Right -split '\.dev'
    $base = ([version]$a[0]).CompareTo([version]$b[0])
    if ($base) { return $base }
    if ($a.Length -eq 1 -and $b.Length -eq 1) { return 0 }
    if ($a.Length -eq 1) { return 1 }; if ($b.Length -eq 1) { return -1 }
    return ([long]$a[1]).CompareTo([long]$b[1])
}
function Replace-Member([string]$Name, [string]$NewPath) {
    $targetPath = [IO.Path]::GetFullPath((Join-Path $destinationPath $Name))
    if (-not $targetPath.StartsWith($destinationPath + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid member path' }
    $backupPath = Join-Path $stage ('backup-' + $journal.Count)
    $record = @{Target=$targetPath; Backup=$backupPath; Installed=$false}
    $journal.Add($record) | Out-Null
    if (Test-Path -LiteralPath $targetPath) { Move-Item -LiteralPath $targetPath -Destination $backupPath }
    if ($NewPath) {
        Move-Item -LiteralPath $NewPath -Destination $targetPath
        $record.Installed = $true
    }
}
$resultCode = 10
$lock = $null; $stage = $null; $complete = $false; $rollbackOK = $true
$lockHeld = $false; $createdDestination = $false; $observedMarker = $null
$journal = New-Object 'System.Collections.Generic.List[object]'
try {
    $source = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
    $destinationPath = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
    if ($destinationPath.Length -le 3 -or $source -eq $destinationPath -or $destinationPath.StartsWith($source + '\', [StringComparison]::OrdinalIgnoreCase) -or $source.StartsWith($destinationPath + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid destination' }
    $dataPath = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'BongoCatChat'))
    if ($dataPath -eq $destinationPath -or $dataPath.StartsWith($destinationPath + '\', [StringComparison]::OrdinalIgnoreCase) -or $destinationPath.StartsWith($dataPath + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Installation must be outside chat data' }
    Assert-NoLinks $source -Tree
    Assert-NoLinks $destinationPath
    $incoming = Get-Manifest (Join-Path $source '.bongo-cat-chat-install')
    $sourceVersion = Join-Path $source "versions/$($incoming.active)"
    foreach ($required in @('BongoCatChat.exe', 'uninstall.ps1', "versions/$($incoming.active)/BongoCatChatApp/BongoCatChatApp.exe")) {
        if (-not (Test-Path -LiteralPath (Join-Path $source $required) -PathType Leaf)) { throw 'Incomplete source bundle' }
    }
    $current = $null; $legacy = $false
    if (Test-Path -LiteralPath $destinationPath) {
        if (-not (Test-Path -LiteralPath $destinationPath -PathType Container)) { throw 'Destination is not a directory' }
        $markerPath = Join-Path $destinationPath '.bongo-cat-chat-install'
        if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
            Assert-NoLinks $markerPath
            $observedMarker = Get-Content -LiteralPath $markerPath -Raw
            $legacy = $observedMarker.Trim() -eq 'BongoCatChat-0.1.0.dev1'
            if ($legacy) { $current = @{active='0.1.0.dev1'; previous=$null} }
            else { $current = Get-Manifest $markerPath }
            if (-not (Test-Path -LiteralPath (Join-Path $destinationPath 'BongoCatChat.exe') -PathType Leaf)) { throw 'Existing installation is incomplete' }
            $resultCode = 30
            if ((Compare-AppVersion $incoming.active $current.active) -lt 0) { throw 'A newer version is already installed' }
        } elseif (Get-ChildItem -LiteralPath $destinationPath -Force) { throw 'Destination contains unrelated files' }
    }
    $resultCode = 10
    foreach ($member in @('versions', '.updates', '_internal', 'BongoCatChat.exe', 'uninstall.ps1', 'Uninstall.exe', '.bongo-cat-chat-run.lock')) { Assert-NoLinks (Join-Path $destinationPath $member) -Tree }
    if (-not $ShortcutName -or $ShortcutName.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) { throw 'Invalid shortcut name' }
    $shortcutPath = Join-Path $env:APPDATA "Microsoft/Windows/Start Menu/Programs/$ShortcutName.lnk"
    if (-not $NoShortcut -and (Test-Path -LiteralPath $shortcutPath)) {
        Initialize-ShortcutInterop
        $shortcutTarget = [BongoChatShortcut]::Read($shortcutPath)
        if ($shortcutTarget -ne (Join-Path $destinationPath 'BongoCatChat.exe')) { $resultCode = 11; throw 'Another installation owns the shortcut' }
    }
    $resultCode = 20
    $active = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($destinationPath + '\', [StringComparison]::OrdinalIgnoreCase) }
    if ($active) { throw 'Close Bongo Cat Chat before installing' }
    $resultCode = 40
    $createdDestination = -not (Test-Path -LiteralPath $destinationPath)
    New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
    $lock = [IO.File]::Open((Join-Path $destinationPath '.bongo-cat-chat-run.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
    $resultCode = 20
    $lock.Lock(0, 1)
    $lockHeld = $true
    $resultCode = 40
    $markerPath = Join-Path $destinationPath '.bongo-cat-chat-install'
    $lockedMarker = $null
    if (Test-Path -LiteralPath $markerPath) { $lockedMarker = Get-Content -LiteralPath $markerPath -Raw }
    if ($lockedMarker -cne $observedMarker) { throw 'Installation changed during preparation; retry setup' }
    if (-not $current -and (Get-ChildItem -LiteralPath $destinationPath -Force | Where-Object { $_.Name -ne '.bongo-cat-chat-run.lock' })) { throw 'Destination changed during preparation; retry setup' }
    $stage = Join-Path $destinationPath ('.bongo-setup-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-Item -LiteralPath $sourceVersion -Destination (Join-Path $stage 'version') -Recurse
    $rootFiles = @('BongoCatChat.exe', 'uninstall.ps1')
    if (Test-Path -LiteralPath (Join-Path $source 'Uninstall.exe')) { $rootFiles += 'Uninstall.exe' }
    foreach ($name in $rootFiles) { Copy-Item -LiteralPath (Join-Path $source $name) -Destination $stage }
    $previous = $null
    if ($current -and -not $legacy) {
        $previous = $current.active
        if ($current.active -eq $incoming.active) { $previous = $current.previous }
    }
    @{schema=2;active=$incoming.active;previous=$previous} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stage '.bongo-cat-chat-install') -Encoding utf8
    New-Item -ItemType Directory -Path (Join-Path $destinationPath 'versions') -Force | Out-Null
    Replace-Member "versions/$($incoming.active)" (Join-Path $stage 'version')
    foreach ($name in $rootFiles) { Replace-Member $name (Join-Path $stage $name) }
    if ($legacy) { Replace-Member '_internal' '' }
    # Switch the active version only after every replacement is in place.
    Replace-Member '.bongo-cat-chat-install' (Join-Path $stage '.bongo-cat-chat-install')
    if (-not $NoShortcut) {
        New-Item -ItemType Directory -Path (Split-Path $shortcutPath -Parent) -Force | Out-Null
        Initialize-ShortcutInterop
        [BongoChatShortcut]::Write($shortcutPath, (Join-Path $destinationPath 'BongoCatChat.exe'), $destinationPath)
    }
    $complete = $true
    $resultCode = 0
    Write-Output 'Installed. Existing chat history and settings are retained.'
} catch {
    Write-Output $_.Exception.Message
    for ($i = $journal.Count - 1; $i -ge 0; $i--) {
        $record = $journal[$i]
        try {
            if ($record.Installed -and (Test-Path -LiteralPath $record.Target)) {
                Assert-NoLinks $record.Target -Tree
                Remove-Item -LiteralPath $record.Target -Recurse -Force
            }
            if (Test-Path -LiteralPath $record.Backup) { Move-Item -LiteralPath $record.Backup -Destination $record.Target }
        } catch { $rollbackOK = $false; Write-Output 'Recovery files retained for repair.' }
    }
} finally {
    if ($stage -and ($complete -or $rollbackOK) -and (Test-Path -LiteralPath $stage)) {
        # stage was created under the verified destination, never a user-supplied delete root.
        try { Assert-NoLinks $stage -Tree; Remove-Item -LiteralPath $stage -Recurse -Force } catch { Write-Output 'Temporary setup files retained.' }
    }
    if ($lock) { $lock.Dispose() }
    # Failed first installs must be retryable. Remove only our lock and empty
    # directories, never recursively delete the destination or another install.
    if (-not $complete -and $lockHeld -and -not $current -and $rollbackOK -and -not (Test-Path -LiteralPath (Join-Path $destinationPath '.bongo-cat-chat-install'))) {
        try {
            Assert-NoLinks $destinationPath
            Remove-Item -LiteralPath (Join-Path $destinationPath '.bongo-cat-chat-run.lock') -Force -ErrorAction SilentlyContinue
            $emptyVersions = Join-Path $destinationPath 'versions'
            if ((Test-Path -LiteralPath $emptyVersions -PathType Container) -and -not (Get-ChildItem -LiteralPath $emptyVersions -Force)) {
                Remove-Item -LiteralPath $emptyVersions
            }
            if ($createdDestination -and -not (Get-ChildItem -LiteralPath $destinationPath -Force)) { Remove-Item -LiteralPath $destinationPath }
        } catch { Write-Output 'Empty setup directory retained.' }
    }
}
exit $resultCode
