$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Apps = Split-Path $Root -Parent
$Current = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$System = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
$Admins = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
$Paths = @((Join-Path $Root 'config.json'), (Join-Path $Root 'state'), (Join-Path $Root 'work'), (Join-Path $Root 'logs'), (Join-Path $Apps 'NapCat-runtime/napcat/config'), (Join-Path $Apps 'NapCat-runtime/profile'), (Join-Path $Apps 'NapCat-runtime/napcat/cache'))
$Paths += @((Join-Path $Apps 'NapCat-runtime/napcat-console.log'), (Join-Path $Apps 'NapCat-runtime/start-stdout.log'), (Join-Path $Apps 'NapCat-runtime/start-stderr.log'))
$migration = Get-Content (Join-Path $Root 'state/migration.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$Paths += $migration.archive
$failedPreparation = Join-Path $Apps 'backups/qqbot-legacy-20260921-174138'
if (Test-Path $failedPreparation) { $Paths += $failedPreparation }
foreach ($Path in $Paths) {
    if (-not (Test-Path -LiteralPath $Path)) { continue }
    $item = Get-Item -LiteralPath $Path
    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) { $acl.RemoveAccessRuleSpecific($rule) }
    foreach ($sid in @($Current, $System, $Admins)) {
        if ($item.PSIsContainer) {
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        } else {
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'Allow')
        }
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}
Write-Output 'Sensitive project paths restricted to the current Windows user, SYSTEM, and Administrators.'
