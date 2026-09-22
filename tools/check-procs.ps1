Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*QQBot-service*app.py*' } |
  ForEach-Object { Write-Output ("PID={0} PPID={1} CREATED={2}" -f $_.ProcessId, $_.ParentProcessId, $_.CreationDate) }
$conn = Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 3000,3001,3002 }
foreach ($c in $conn) { Write-Output ("PORT {0} OWNER {1}" -f $c.LocalPort, $c.OwningProcess) }
