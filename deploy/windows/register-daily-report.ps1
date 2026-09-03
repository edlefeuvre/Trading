# register-daily-report.ps1 - Task Scheduler task 'TRADING-daily': the 07:00 (local) Trading Book
# report to the Digest topic. Book-level: every strategy, plus anything on the exchange that
# matches no strategy ticket (OUTSIDE STRATEGIES).
param([switch]$Unregister, [string]$Python = "", [string]$At = "07:00")
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot)
$name = "TRADING-daily"
if ($Unregister) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; Write-Host "removed $name"; exit 0 }
if (-not $Python) {
  $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
  if (-not $Python) { $Python = "C:\Program Files\Python312\python.exe" }
}
$PythonW = Join-Path (Split-Path $Python) "pythonw.exe"
if (Test-Path -LiteralPath $PythonW) { $Python = $PythonW }
$action  = New-ScheduledTaskAction -Execute $Python -Argument "-m common.reports.daily" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "registered $name : daily at $At local, exe $Python, cwd $repo"
