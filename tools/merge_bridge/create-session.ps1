param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $Path) {
    if (@(Get-ChildItem -LiteralPath $Path -Force).Count) { throw 'Session already contains state; do not reattach' }
} else { New-Item -ItemType Directory -Path $Path | Out-Null }
$acl = [System.Security.AccessControl.DirectorySecurity]::new()
$acl.SetAccessRuleProtection($true,$false)
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl.SetOwner($sid)
foreach ($identity in @($sid, [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($identity,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
    $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $Path -AclObject $acl
if (-not (Get-Acl -LiteralPath $Path).AreAccessRulesProtected) { throw 'Session ACL unverified' }
