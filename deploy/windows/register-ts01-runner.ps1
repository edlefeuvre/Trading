# register-ts01-runner.ps1 - Task Scheduler task 'TS01-runner': one PAPER cycle every 15 minutes,
# 30 s after each bar close, from the repo root. Runs alongside the old 'CHoCH watcher' task
# until both agree; then disable the old one by hand (Disable-ScheduledTask 'CHoCH watcher').
#
#   .\deploy\windows\register-ts01-runner.ps1            # register / update
#   .\deploy\windows\register-ts01-runner.ps1 -Unregister
#   .\deploy\windows\register-ts01-runner.ps1 -RunNow    # register and fire one cycle immediately
param([switch]$Unregister, [switch]$RunNow, [string]$Python = "")
$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot)
$name = "TS01-runner"
if ($Unregister) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; Write-Host "removed $name"; exit 0 }

if (-not $Python) {
  $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
  if (-not $Python) { $Python = "C:\Program Files\Python312\python.exe" }
}
if (-not (Test-Path -LiteralPath $Python)) { Write-Error "python not found at $Python"; exit 1 }
# run the cycle with pythonw.exe (no console window): a visible window can be closed mid-cycle,
# which kills the process (task result 0xC000013A). Output goes to the JSONL log, not a console.
$PythonW = Join-Path (Split-Path $Python) "pythonw.exe"
if (Test-Path -LiteralPath $PythonW) { $Exe = $PythonW } else { $Exe = $Python }

# pyyaml is the runner's only third-party dependency
& $Python -c "import yaml" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "installing pyyaml..."; & $Python -m pip install --quiet pyyaml }

$action = New-ScheduledTaskAction -Execute $Exe `
  -Argument "-m strategies.TS01_CHoCH_ICT_15m_Binance_USDCp.src.runner" -WorkingDirectory $repo
# start at the next hh:00:30 and repeat every 15 min -> fires at :00:30, :15:30, :30:30, :45:30
$start = (Get-Date).Date.AddHours((Get-Date).Hour + 1).AddSeconds(30)
$trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "registered $name : every 15 min from $($start.ToString('HH:mm:ss')), exe $Exe, cwd $repo"
Write-Host "logs: $repo\strategies\TS01_CHoCH_ICT_15m_Binance_USDCp\logs\TS01-runner.jsonl"
if ($RunNow) { Start-ScheduledTask -TaskName $name; Write-Host "started one cycle now" }
