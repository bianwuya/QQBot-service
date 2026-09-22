Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*QQBot-service*app.py*' } |
  ForEach-Object { Write-Output ("PROC {0} CMD {1}" -f $_.ProcessId, $_.CommandLine) }
try {
  $r = Invoke-WebRequest -Uri 'http://127.0.0.1:3002/healthz' -TimeoutSec 10 -UseBasicParsing
  Write-Output ("HEALTH {0} {1}" -f $r.StatusCode, $r.Content)
} catch {
  Write-Output ("HEALTH-ERROR {0}" -f $_.Exception.Message)
}
