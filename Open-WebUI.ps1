$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# Start/reuse only our own services and wait for actual HTTP readiness.
& (Join-Path $PSScriptRoot 'start.ps1')
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
& $python -X utf8 (Join-Path $PSScriptRoot 'tools/check-login.py') --refresh
if ($LASTEXITCODE -ne 0) { throw 'NapCat login/QR check failed. The browser was not opened with a broken backend.' }
$Nap = Join-Path (Split-Path $PSScriptRoot -Parent) 'NapCat-runtime'
$cfg = Get-Content (Join-Path $Nap 'napcat/config/webui.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($cfg.host -ne '127.0.0.1') { throw 'Unexpected WebUI host' }
$url = 'http://127.0.0.1:' + $cfg.port + '/webui?token=' + [Uri]::EscapeDataString($cfg.token) + '&loginRefresh=' + [DateTime]::UtcNow.Ticks
Start-Process $url
# Never print the token, signed credential, or QR login URL.
