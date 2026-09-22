$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = $PSScriptRoot
$Nap = Join-Path (Split-Path $Root -Parent) 'NapCat-runtime'
$napExe = Join-Path $Nap 'node.exe'
$existing = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $napExe })
if ($existing.Count -eq 0) {
    $env:NAPCAT_USERDATA_PATH = Join-Path $Nap 'profile'
    $env:NAPCAT_WORKDIR = Join-Path $Nap 'napcat'
    $env:NAPCAT_DISABLE_TIME_SYNC = '1'
    Start-Process -FilePath $napExe -ArgumentList ('"' + (Join-Path $Nap 'index.js') + '"') -WorkingDirectory $Nap -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Nap 'start-stdout.log') -RedirectStandardError (Join-Path $Nap 'start-stderr.log') | Out-Null
}
$running = $false
try {
    $h = Invoke-RestMethod 'http://127.0.0.1:3002/healthz' -TimeoutSec 2
    if ($h.service -ne 'qqbot-service') { throw 'Port 3002 belongs to another service' }
    $running = $true
} catch {
    $listener = Get-NetTCPConnection -LocalPort 3002 -State Listen -ErrorAction SilentlyContinue
    if ($listener) { throw 'Port 3002 occupied; refusing duplicate start' }
}
if (-not $running) {
    $exe = Join-Path $Root '.venv/Scripts/python.exe'
    Start-Process -FilePath $exe -ArgumentList ('-X utf8 "' + (Join-Path $Root 'app.py') + '"') -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Root 'logs/start-stdout.log') -RedirectStandardError (Join-Path $Root 'logs/start-stderr.log') | Out-Null
}
function Wait-LocalHttp([string]$Uri, [int]$Seconds, [string]$Label) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 300
    } while ([DateTime]::UtcNow -lt $deadline)
    throw ($Label + ' did not become ready. Check this project logs; no other QQ process was stopped.')
}
$webConfig = Get-Content (Join-Path $Nap 'napcat/config/webui.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($webConfig.host -ne '127.0.0.1') { throw 'Unexpected WebUI host; refusing to expose local credentials' }
Wait-LocalHttp ('http://127.0.0.1:' + $webConfig.port + '/webui') 25 'NapCat WebUI'
Wait-LocalHttp 'http://127.0.0.1:3002/healthz' 10 'QQBot service'
$webListener = Get-NetTCPConnection -LocalPort $webConfig.port -State Listen -ErrorAction Stop | Where-Object { $_.LocalAddress -eq '127.0.0.1' } | Select-Object -First 1
if (-not $webListener) { throw 'Expected loopback WebUI listener was not found' }
$webProcess = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $webListener.OwningProcess)
if ($webProcess.ExecutablePath -ne $napExe) { throw 'WebUI port is owned by another executable' }
Write-Output 'QQBot and NapCat HTTP endpoints are ready. QQ login is checked separately. No ordinary QQ process was stopped.'
