param(
    [Parameter(Mandatory=$true)][ValidateSet('Show','Inspect','Cleanup')][string]$Action,
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory
)
# Run with Windows PowerShell 5.1. A temporary, unique per-user AUMID is used.
# No real messages, product shortcut, notification preferences or game access.
$ErrorActionPreference = 'Stop'
$probeRoot = Split-Path $PSScriptRoot -Parent
$evidence = [IO.Path]::GetFullPath($EvidenceDirectory)
$marker = Join-Path $evidence 'toast-registration.json'
$appId = 'BongoCatChat.NotificationProbe.20261016'
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'Bongo Cat Chat Notification Probe 20261016.lnk'
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
$null = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime]

if ($Action -eq 'Show') {
    if ((Test-Path -LiteralPath $shortcut) -or (Test-Path -LiteralPath $marker)) {
        throw 'Probe registration already exists. Inspect or clean it up first.'
    }
    $python = Join-Path $probeRoot '.venv/Scripts/pythonw.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Repository venv is required.' }
    New-Item -ItemType Directory -Path $evidence -Force | Out-Null
    Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
public static class NotificationProbeShortcut {
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")] class ShellLink {}
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface ILink {
        void GetPath([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder p,int s,IntPtr d,uint f);
        void GetIDList(out IntPtr p); void SetIDList(IntPtr p);
        void GetDescription([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder p,int s);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string p);
        void GetWorkingDirectory([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder p,int s);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string p);
        void GetArguments([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder p,int s);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string p);
        void GetHotkey(out short p); void SetHotkey(short p);
        void GetShowCmd(out int p); void SetShowCmd(int p);
        void GetIconLocation([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder p,int s,out int i);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string p,int i);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string p,uint r);
        void Resolve(IntPtr w,uint f); void SetPath([MarshalAs(UnmanagedType.LPWStr)] string p);
    }
    [StructLayout(LayoutKind.Sequential)] struct Key { public Guid fmtid; public uint pid; }
    [StructLayout(LayoutKind.Explicit, Size=24)] struct Value {
        [FieldOffset(0)] public ushort type;
        [FieldOffset(8)] public IntPtr text;
    }
    [ComImport,Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IStore {
        void GetCount(out uint n); void GetAt(uint i,out Key k);
        void GetValue(ref Key k,out Value v); void SetValue(ref Key k,ref Value v); void Commit();
    }
    public static void Write(string path,string target,string args,string appId) {
        object link = new ShellLink();
        IntPtr text = Marshal.StringToCoTaskMemUni(appId);
        try {
            ((ILink)link).SetPath(target); ((ILink)link).SetArguments(args);
            var key = new Key { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
            var value = new Value { type = 31, text = text };
            ((IStore)link).SetValue(ref key,ref value); ((IStore)link).Commit();
            ((IPersistFile)link).Save(path,true);
        } finally { Marshal.FreeCoTaskMem(text); Marshal.FinalReleaseComObject(link); }
    }
}
'@
    $arguments = '"{0}" --data "{1}"' -f (Join-Path $PSScriptRoot 'probe_notifications.py'), (Join-Path $evidence 'shortcut-window')
    [NotificationProbeShortcut]::Write($shortcut,$python,$arguments,$appId)
    @{ shortcut=$shortcut; app_id=$appId; sha256=(Get-FileHash -LiteralPath $shortcut -Algorithm SHA256).Hash } |
        ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8
    $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId)
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text>Bongo Cat Chat notification probe</text><text>Synthetic incoming message. Windows notification-center test.</text></binding></visual></toast>')
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    $toast.Tag = 'probe'
    $toast.Group = 'validation'
    $toast.ExpirationTime = [DateTimeOffset]::Now.AddMinutes(10)
    $notifier.Show($toast)
    Start-Sleep -Seconds 3
}

if (-not (Test-Path -LiteralPath $marker)) { throw 'This run did not register the probe shortcut.' }
$registration = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
if ($registration.app_id -ne $appId -or $registration.shortcut -ne $shortcut) { throw 'Registration mismatch.' }

if ($Action -eq 'Cleanup') {
    if (Test-Path -LiteralPath $shortcut) {
        if ((Get-FileHash -LiteralPath $shortcut -Algorithm SHA256).Hash -ne $registration.sha256) {
            throw 'The shortcut changed; refusing to delete it.'
        }
        # Exact owned file only; no recursive deletion or computed directory removal.
        Remove-Item -LiteralPath $shortcut
    }
    [Windows.UI.Notifications.ToastNotificationManager]::History.Clear($appId)
    @{ cleanup=$true; shortcut_remaining=(Test-Path -LiteralPath $shortcut);
       history_count=@([Windows.UI.Notifications.ToastNotificationManager]::History.GetHistory($appId)).Count } |
        ConvertTo-Json | Tee-Object -FilePath (Join-Path $evidence 'toast-cleanup.json')
    Remove-Item -LiteralPath $marker
    return
}

$history = @([Windows.UI.Notifications.ToastNotificationManager]::History.GetHistory($appId))
$result = @{ app_id=$appId; action=$Action; notifier_setting=[string]([Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Setting);
    history_count=$history.Count; own_tag_present=@($history | Where-Object { $_.Tag -eq 'probe' -and $_.Group -eq 'validation' }).Count -gt 0;
    synthetic_only=$true; banner_visually_confirmed=$false; click_activation_verified=$false }
$result | ConvertTo-Json | Tee-Object -FilePath (Join-Path $evidence ('toast-' + $Action.ToLowerInvariant() + '.json'))
