# register-secrets-sync-task.ps1 - hourly Task Scheduler job 'TS-secrets-sync' running sync-secrets.ps1.
# Optional. Without it, rotation = run sync-secrets.ps1 by hand after updating Bitwarden.
param([int]$EveryMinutes = 60)
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot "sync-secrets.ps1"
$action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"" -WorkingDirectory (Split-Path (Split-Path $PSScriptRoot))
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "TS-secrets-sync" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "registered TS-secrets-sync every $EveryMinutes min (runs as the logged-on user, so auto-logon matters)"
