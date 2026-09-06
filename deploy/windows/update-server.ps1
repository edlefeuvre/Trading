# update-server.ps1 - bring the trading server up to date and work through the
# outstanding tasks in order. Read-only where it can be; it places no orders.
#
#   .\deploy\windows\update-server.ps1                 # checks + reports, registers nothing
#   .\deploy\windows\update-server.ps1 -RegisterTasks  # also register any missing scheduled task
#   .\deploy\windows\update-server.ps1 -Commit         # also git add/commit/push
#
# Every step prints PASS / WARN / FAIL and the script keeps going, so one failure
# does not hide the rest. Nothing here changes params.yaml or places an order.
param(
  [switch]$RegisterTasks,
  [switch]$Commit,
  [string]$ReportDir = "$env:USERPROFILE\Downloads"
)
$ErrorActionPreference = 'Continue'
$repo = Split-Path (Split-Path $PSScriptRoot)
Set-Location $repo
$fails = @()
$warns = @()

function Step($n, $t) { Write-Host ""; Write-Host ("=" * 66); Write-Host "  $n. $t"; Write-Host ("=" * 66) }
function Pass($m) { Write-Host "  PASS  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  WARN  $m" -ForegroundColor Yellow; $script:warns += $m }
function Fail($m) { Write-Host "  FAIL  $m" -ForegroundColor Red;   $script:fails += $m }

Write-Host ""
Write-Host "Trading server update - $(Get-Date -Format 'yyyy-MM-dd HH:mm') local"
Write-Host "repo $repo"

# ---------------------------------------------------------------- 1. version
Step 1 "Version and integrity"
$sv = Select-String -Path "strategies\TS01_CHoCH_ICT_15m_Binance_USDCp\STRATEGY.md" -Pattern '^version:' | Select-Object -First 1
$pv = Select-String -Path "strategies\TS01_CHoCH_ICT_15m_Binance_USDCp\config\params.yaml" -Pattern '^\s+version:' | Select-Object -First 1
Write-Host "  STRATEGY.md $($sv.Line.Trim())"
Write-Host "  params.yaml $($pv.Line.Trim())"
python bin\check-strategy --all
if ($LASTEXITCODE -eq 0) { Pass "check-strategy consistent" } else { Fail "check-strategy failed" }
python -m pytest -q strategies\TS01_CHoCH_ICT_15m_Binance_USDCp\src\tests
if ($LASTEXITCODE -eq 0) { Pass "tests green" } else { Fail "tests failed" }

# ------------------------------------------------------------ 2. scheduled tasks
Step 2 "Scheduled tasks"
$want = @(
  @{ Name = 'TS01-runner';  Script = 'register-ts01-runner.ps1'  },
  @{ Name = 'TS01-weekly';  Script = 'register-ts01-weekly.ps1'  },
  @{ Name = 'TRADING-daily';Script = 'register-daily-report.ps1' }
)
foreach ($w in $want) {
  $t = Get-ScheduledTask -TaskName $w.Name -ErrorAction SilentlyContinue
  if ($t) {
    $i = Get-ScheduledTaskInfo -TaskName $w.Name -ErrorAction SilentlyContinue
    $res = $i.LastTaskResult
    $line = "$($w.Name): state $($t.State), last run $($i.LastRunTime), result $res, next $($i.NextRunTime)"
    if ($res -eq 0) { Pass $line } else { Warn $line }
  } elseif ($RegisterTasks) {
    Write-Host "  registering $($w.Name) ..."
    powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot $w.Script)
    if ($LASTEXITCODE -eq 0) { Pass "$($w.Name) registered" } else { Fail "$($w.Name) registration failed" }
  } else {
    Warn "$($w.Name) MISSING - re-run with -RegisterTasks to create it"
  }
}

# ------------------------------------------------------------- 3. credentials
Step 3 "Credentials and exchange read"
python -m common.exchange.binance --key SERVER_RO --restrictions
if ($LASTEXITCODE -eq 0) { Pass "SERVER_RO reachable" } else { Fail "SERVER_RO check failed" }

# ------------------------------------------------------- 4. detection is alive
Step 4 "Detection check (state-free, sends nothing)"
python bin\scan-now --bars 400
if ($LASTEXITCODE -eq 0) { Pass "scan-now ran" } else { Fail "scan-now failed" }

# ------------------------------------------------------------ 5. trade reports
Step 5 "Trade reports and the paper-track register"
python bin\trade-report --bars 400
if ($LASTEXITCODE -eq 0) { Pass "trade-report ran" } else { Fail "trade-report failed" }

# ------------------------------------------------------------------- 6. study
Step 6 "Hours and blocks study"
$stamp = Get-Date -Format 'yyyyMMdd'
$out = Join-Path $ReportDir "$stamp-TS01-blocks-days-study.html"
python bin\study-hours --html $out
if ($LASTEXITCODE -eq 0) { Pass "study written to $out" } else { Fail "study-hours failed" }

# ------------------------------------------------------------- 7. daily report
Step 7 "Daily book report (sends to the Digest topic)"
python -m common.reports.daily
if ($LASTEXITCODE -eq 0) { Pass "daily report sent" } else { Fail "daily report failed" }

# --------------------------------------------------------------------- 8. git
Step 8 "Git"
git status --short
$dirty = (git status --porcelain) -ne $null
if ($Commit) {
  if ($dirty) {
    git add -A
    git commit -m "TS01 v1.20: study UTC blocks, update-server.ps1"
    git push
    if ($LASTEXITCODE -eq 0) { Pass "committed and pushed" } else { Fail "push failed" }
  } else { Pass "nothing to commit" }
} elseif ($dirty) {
  Warn "working tree dirty - re-run with -Commit, or commit by hand"
} else { Pass "working tree clean" }

# ----------------------------------------------------------------- summary
Write-Host ""
Write-Host ("=" * 66)
Write-Host "  SUMMARY"
Write-Host ("=" * 66)
if ($fails.Count -eq 0) { Write-Host "  no failures" -ForegroundColor Green }
foreach ($f in $fails) { Write-Host "  FAIL  $f" -ForegroundColor Red }
foreach ($w in $warns) { Write-Host "  WARN  $w" -ForegroundColor Yellow }
Write-Host ""
Write-Host "  Still needing a human, not this script:"
Write-Host "   - Rotate the Telegram bot token (it was pasted into a chat) and update"
Write-Host "     Paperclip's copy in .config\telegram-webhook."
Write-Host "   - Fill the exchange fields in the AVAX journal entry:"
Write-Host "       python -m common.exchange.binance --history AVAXUSDC --hours 48"
Write-Host "   - Commit the Pine source to strategies\TS01_*\pine\ and fill the pine"
Write-Host "     column in results\trade-reports\TS01-paper-track.csv."
Write-Host "   - Confirm auto-logon and power settings survive a reboot."
Write-Host ""
Write-Host "  Parked for the Sunday review, deliberately not applied:"
Write-Host "   - pool_consumed_cancel: implement it in code or drop it from the desk."
Write-Host "   - Unattended R factor 0.5 (recommended by look #9, not written to params)."
Write-Host "   - daily_loss_stop_r is documented but enforced nowhere."
Write-Host ""
