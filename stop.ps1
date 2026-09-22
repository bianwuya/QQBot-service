$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Nap = Join-Path (Split-Path $Root -Parent) 'NapCat-runtime'
$napExe = Join-Path $Nap 'node.exe'
$app = Join-Path $Root 'app.py'
$venvPython = Join-Path $Root '.venv/Scripts/python.exe'
$targets = @(Get-CimInstance Win32_Process | Where-Object {
    ($_.ExecutablePath -eq $napExe) -or
    (($_.ExecutablePath -eq $venvPython -or $_.ExecutablePath -eq 'C:\Python314\python.exe') -and $_.CommandLine -and $_.CommandLine.Contains($app))
})
foreach ($p in $targets) {
    Stop-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
}
Write-Output ('Stopped only matching QQBot/NapCat processes: ' + $targets.Count)
