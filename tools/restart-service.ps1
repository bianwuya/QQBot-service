$ErrorActionPreference='Stop'
$procs=Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*QQBot-service*app.py*' }
foreach($proc in $procs){ Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 3
Start-Process -FilePath 'F:\Apps\QQBot-service\.venv\Scripts\python.exe' -ArgumentList '-X','utf8','F:\Apps\QQBot-service\app.py' -WorkingDirectory 'F:\Apps\QQBot-service' -WindowStyle Hidden -RedirectStandardOutput 'F:\Apps\QQBot-service\logs\service-stdout.log' -RedirectStandardError 'F:\Apps\QQBot-service\logs\service-stderr.log'
Start-Sleep 8
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*QQBot-service*app.py*' } | Select-Object ProcessId,ParentProcessId,CreationDate | Format-List
(Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:3002/healthz -TimeoutSec 5).Content
