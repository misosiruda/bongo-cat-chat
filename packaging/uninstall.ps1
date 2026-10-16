param([string]$Destination = $PSScriptRoot, [switch]$NoShortcut, [string]$ShortcutName = 'Bongo Cat Chat')
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
    [StructLayout(LayoutKind.Sequential)] private struct Key { public Guid fmtid; public uint pid; }
    [StructLayout(LayoutKind.Explicit, Size=24)] private struct Value {
        [FieldOffset(0)] public ushort type;
        [FieldOffset(8)] public IntPtr text;
    }
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IStore {
        void GetCount(out uint count); void GetAt(uint index, out Key key);
        void GetValue(ref Key key, out Value value); void SetValue(ref Key key, ref Value value); void Commit();
    }
    [DllImport("ole32.dll")] private static extern int PropVariantClear(ref Value value);
    public const string AppId = "BongoCatChat.Desktop";
    public static string ReadAppId(string path) {
        object link = new ShellLink();
        var value = new Value();
        try {
            ((IPersistFile)link).Load(path, 0);
            var key = new Key { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
            ((IStore)link).GetValue(ref key, out value);
            return value.type == 31 ? Marshal.PtrToStringUni(value.text) : "";
        } finally { PropVariantClear(ref value); Marshal.FinalReleaseComObject(link); }
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
            ((ILink)link).SetIconLocation(target, 0);
            var key = new Key { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
            var value = new Value { type = 31, text = Marshal.StringToCoTaskMemUni(AppId) };
            try { ((IStore)link).SetValue(ref key, ref value); ((IStore)link).Commit(); }
            finally { Marshal.FreeCoTaskMem(value.text); }
            ((IPersistFile)link).Save(path, true);
        } finally { Marshal.FinalReleaseComObject(link); }
    }
}
"@
}
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
    # Shortcut inspection/deletion can fail independently. Preserve the app and
    # its verification marker until this succeeds so native removal is retryable.
    if (-not $NoShortcut) {
        $shortcutPath = Join-Path $env:APPDATA "Microsoft/Windows/Start Menu/Programs/$ShortcutName.lnk"
        if (Test-Path -LiteralPath $shortcutPath) {
            Initialize-ShortcutInterop
            $shortcutTarget = [BongoChatShortcut]::Read($shortcutPath)
            if (-not $shortcutTarget) { throw 'Cannot inspect the Start Menu shortcut; retry uninstall' }
            $shortcutId = [BongoChatShortcut]::ReadAppId($shortcutPath)
            if ($shortcutTarget -eq (Join-Path $target 'BongoCatChat.exe') -and (-not $shortcutId -or $shortcutId -eq [BongoChatShortcut]::AppId)) {
                # Only the genuine per-user Start Menu owns OS registration.
                # Isolated installer tests redirect APPDATA and never touch OS history.
                $realPrograms = [Environment]::GetFolderPath('Programs')
                if ($shortcutId -eq [BongoChatShortcut]::AppId -and (Split-Path $shortcutPath -Parent) -eq $realPrograms) {
                    try {
                        $null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
                        [Windows.UI.Notifications.ToastNotificationManager]::History.RemoveGroup('incoming', [BongoChatShortcut]::AppId)
                    } catch { Write-Output 'Windows notification cleanup was unavailable; app data is retained.' }
                }
                Remove-Item -LiteralPath $shortcutPath
            }
        }
    }
    foreach ($name in $members) {
        $item = Join-Path $target $name
        if (Test-Path -LiteralPath $item) { Remove-Item -LiteralPath $item -Recurse -Force }
    }
    $resultCode = 0
    Write-Output 'App removed. Chat history and settings are retained.'
} catch { Write-Output $_.Exception.Message }
finally { if ($lock) { $lock.Dispose() } }
if ($resultCode -eq 0) { Remove-Item -LiteralPath (Join-Path $target '.bongo-cat-chat-run.lock') -Force -ErrorAction SilentlyContinue }
exit $resultCode
