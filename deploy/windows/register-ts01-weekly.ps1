# register-ts01-weekly.ps1 - Task Scheduler task 'TS01-weekly': the Sunday programme,
# Sundays 08:00 local (06:00 UTC in summer), before the Sunday pass. Proposes tiers to the
# Digest topic; never changes universe.yaml itself.
param([switch]$Unregister, [string]$Python = "", [string]$At = "08:00")
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot)
$name = "TS01-weekly"
if ($Unregister) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; Write-Host "removed $name"; exit 0 }
if (-not $Python) {
  $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
  if (-not $Python) { $Python = "C:\Program Files\Python312\python.exe" }
}
$action  = New-ScheduledTaskAction -Execute $Python -Argument "-m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.weekly" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At $At
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "registered $name : Sundays $At local, python $Python, cwd $repo (first run downloads ~2.5 years of 15m archive per symbol; cache in %USERPROFILE%\.config\trading-data)"
