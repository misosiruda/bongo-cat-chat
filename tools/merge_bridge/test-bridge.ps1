$ErrorActionPreference = 'Stop'
$output = Join-Path $env:TEMP ('bongo-merge-fixture-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $output | Out-Null
$cache = Join-Path $PSScriptRoot '..\..\artifacts\merge-bridge\newtonsoft-13.0.3'
$zip = Join-Path $PSScriptRoot '..\..\artifacts\merge-bridge\newtonsoft-13.0.3.zip'
if (-not (Test-Path -LiteralPath $zip)) {
    New-Item -ItemType Directory -Force (Split-Path $zip -Parent) | Out-Null
    Invoke-WebRequest -Uri 'https://api.nuget.org/v3-flatcontainer/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nupkg' -OutFile $zip
}
if ((Get-FileHash -LiteralPath $zip).Hash -ne '872FC189E638AB1056555B03AAA38F68BCB54286E221AA646EB1129BABF63C77') { throw 'Unexpected fixture JSON package' }
if (-not (Test-Path (Join-Path $cache 'lib\net45\Newtonsoft.Json.dll'))) {
    Expand-Archive -LiteralPath $zip -DestinationPath $cache
}
$json = Join-Path $cache 'lib\net45\Newtonsoft.Json.dll'
Copy-Item -LiteralPath $json -Destination $output
& "$env:SystemRoot\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:exe "/out:$output\Fixture.exe" "/reference:$json" (Join-Path $PSScriptRoot 'Bridge.cs') (Join-Path $PSScriptRoot 'BridgeFixture.cs')
if ($LASTEXITCODE -ne 0) { throw 'Fixture compilation failed' }
Add-Type -Path (Join-Path $PSScriptRoot '..\..\artifacts\compatibility\Mono.Cecil.dll')
$rp = [Mono.Cecil.ReaderParameters]::new(); $rp.ReadWrite = $true
$a = [Mono.Cecil.AssemblyDefinition]::ReadAssembly((Join-Path $output 'Fixture.exe'),$rp)
try {
    $closure = $a.MainModule.GetTypes() | Where-Object FullName -EQ 'BongoCat.ItemExchange/Closure'
    $closure.Name = '<>c__DisplayClass54_0'
    ($closure.Methods | Where-Object Name -EQ 'Complete').Name = '<ExchangeRoutine>b__2'
    $a.Write()
} finally { $a.Dispose() }
& (Join-Path $output 'Fixture.exe')
if ($LASTEXITCODE -ne 0) { throw 'Bridge fixture failed' }
# A separate disposable fixture directory keeps the legacy consumption ledger intact.
$interactiveOutput = Join-Path $output 'interactive'
New-Item -ItemType Directory $interactiveOutput | Out-Null
Copy-Item -LiteralPath (Join-Path $output 'Fixture.exe'), (Join-Path $output 'Newtonsoft.Json.dll') -Destination $interactiveOutput
& (Join-Path $interactiveOutput 'Fixture.exe') --interactive
if ($LASTEXITCODE -ne 0) { throw 'Interactive bridge fixture failed' }
