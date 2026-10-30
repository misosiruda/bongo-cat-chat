param([string]$GameRoot = 'C:\Program Files (x86)\Steam\steamapps\common\BongoCat', [switch]$Interactive)
$ErrorActionPreference = 'Stop'
$managed = Join-Path $GameRoot 'BongoCat_Data\Managed'
$output = Join-Path $PSScriptRoot '..\..\artifacts\merge-bridge'
$dllName = 'BongoCatChat.MergeBridge.Shared.dll'
if ($Interactive) { $output = Join-Path $output 'app'; $dllName = 'BongoCatChat.MergeBridge.Live.dll' }
$contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'local-contract.json') -Raw | ConvertFrom-Json
foreach ($entry in $contract.files.PSObject.Properties) {
    if (@($entry.Value) -cnotcontains (Get-FileHash -LiteralPath (Join-Path $GameRoot $entry.Name)).Hash.ToLowerInvariant()) { throw 'Unsupported game build for merge bridge' }
}
New-Item -ItemType Directory -Force $output | Out-Null
$names = @('Assembly-CSharp.dll','Assembly-CSharp-firstpass.dll','UnityEngine.CoreModule.dll','Heathen.Steamworks.dll','com.rlabrecque.steamworks.net.dll','Newtonsoft.Json.dll')
$refs = $names | ForEach-Object { '/reference:' + (Join-Path $managed $_) }
& "$env:SystemRoot\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:library "/out:$output\$dllName" $refs (Join-Path $PSScriptRoot 'Bridge.cs')
if ($LASTEXITCODE -ne 0) { throw 'Bridge compilation failed' }
Add-Type -Path (Join-Path $PSScriptRoot '..\..\artifacts\compatibility\Mono.Cecil.dll')
$resolver = [Mono.Cecil.DefaultAssemblyResolver]::new()
$resolver.AddSearchDirectory($managed)
$rp = [Mono.Cecil.ReaderParameters]::new()
$rp.AssemblyResolver = $resolver
$rp.ReadWrite = $true
$a = [Mono.Cecil.AssemblyDefinition]::ReadAssembly((Join-Path $output $dllName), $rp)
try {
    # Unity stripped this unused compiler attribute. Remove it from our own DLL.
    @($a.CustomAttributes | Where-Object {$_.AttributeType.FullName -eq 'System.Runtime.CompilerServices.CompilationRelaxationsAttribute'}) | ForEach-Object { [void]$a.CustomAttributes.Remove($_) }
    $a.Write()
} finally { $a.Dispose() }
$rp.ReadWrite = $false
$a = [Mono.Cecil.AssemblyDefinition]::ReadAssembly((Join-Path $output $dllName), $rp)
try {
    $missing = @($a.MainModule.GetMemberReferences() | Where-Object { ($_ -is [Mono.Cecil.MethodReference] -or $_ -is [Mono.Cecil.FieldReference]) -and $null -eq $_.Resolve() })
    if ($missing.Count) { throw ('Stripped runtime members: ' + ($missing.FullName -join ', ')) }
} finally { $a.Dispose(); $resolver.Dispose() }
Get-FileHash -LiteralPath (Join-Path $output $dllName) | Select-Object Hash
if ($Interactive) {
    @{files=$contract.files;helper_sha256=(Get-FileHash -LiteralPath (Join-Path $output $dllName)).Hash.ToLowerInvariant()} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output 'contract.json') -Encoding utf8
}
