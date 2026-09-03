# register-ts01-daily.ps1 - Task Scheduler task 'TS01-daily': the 07:00 (local) daily report
# to the Digest topic. Reads the exchange with SERVER_RO and the runner's log; sends one message.
param([switch]$Unregister, [string]$Python = "", [string]$At = "07:00")
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot)
$name = "TS01-daily"
if ($Unregister) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; Write-Host "removed $name"; exit 0 }
if (-not $Python) {
  $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
  if (-not $Python) { $Python = "C:\Program Files\Python312\python.exe" }
}
$PythonW = Join-Path (Split-Path $Python) "pythonw.exe"
if (Test-Path -LiteralPath $PythonW) { $Python = $PythonW }
$action  = New-ScheduledTaskAction -Execute $Python -Argument "-m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.daily" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "registered $name : daily at $At local, exe $Python, cwd $repo"
