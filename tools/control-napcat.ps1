param([Parameter(Mandatory=$true)][ValidateSet('start','stop','restart','status')][string]$Action)
$ErrorActionPreference='Stop'
$Root=Split-Path $PSScriptRoot -Parent
$Nap=Join-Path (Split-Path $Root -Parent) 'NapCat-runtime'
$Exe=Join-Path $Nap 'node.exe'
function Get-Target { @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $Exe }) }
if ($Action -eq 'status') { if ((Get-Target).Count -gt 0) { exit 0 } else { exit 1 } }
if ($Action -in @('stop','restart')) {
    foreach($p in (Get-Target)) { Stop-Process -Id $p.ProcessId -ErrorAction Stop }
    $deadline=(Get-Date).AddSeconds(10)
    while ((Get-Target).Count -gt 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
    if ((Get-Target).Count -gt 0) { throw 'NapCat stop not confirmed' }
}
if ($Action -in @('start','restart') -and (Get-Target).Count -eq 0) {
    $env:PATH=(Join-Path $Root 'tools')+';'+$env:PATH
    $env:NAPCAT_USERDATA_PATH=Join-Path $Nap 'profile'
    $env:NAPCAT_WORKDIR=Join-Path $Nap 'napcat'
    $env:NAPCAT_DISABLE_TIME_SYNC='1'
    Start-Process -FilePath $Exe -ArgumentList ('"'+(Join-Path $Nap 'index.js')+'"') -WorkingDirectory $Nap -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Nap 'start-stdout.log') -RedirectStandardError (Join-Path $Nap 'start-stderr.log') | Out-Null
}
Write-Output 'NapCat command completed; verify online/login separately.'
