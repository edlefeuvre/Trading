# setup-telegram.ps1 - create %USERPROFILE%\.config\telegram\<bot>.env files and test them.
#
#   .\deploy\windows\setup-telegram.ps1                      # migrate rickyassist_bot from the old secrets.env, then test
#   .\deploy\windows\setup-telegram.ps1 -Bot newbot -Token 123:ABC   # register another bot (chat id discovered after)
#
# Never prints token values. Run from the repo root.
param(
  [string]$Bot    = "rickyassist_bot",
  [string]$Token  = "",
  [string]$ChatId = "",
  [string]$LegacySecrets = "$env:USERPROFILE\.config\telegram-webhook\secrets.env",
  [string]$LegacyChatId  = "-1003939412847"   # the group the GARCH launcher posts to
)
$ErrorActionPreference = 'Stop'
$dir  = Join-Path $env:USERPROFILE ".config\telegram"
$file = Join-Path $dir "$Bot.env"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

if (-not $Token -and (Test-Path -LiteralPath $LegacySecrets)) {
  $line = Get-Content -LiteralPath $LegacySecrets | Where-Object { $_ -match '^\s*TELEGRAM_RICKYASSIST_BOT_TOKEN\s*=' } | Select -First 1
  if ($line) { $Token = ($line -split '=', 2)[1].Trim().Trim('"').Trim("'"); Write-Host "token: taken from legacy secrets.env" }
  if (-not $ChatId) { $ChatId = $LegacyChatId }
}
if (-not $Token) { Write-Error "no token: pass -Token (from @BotFather) or make sure $LegacySecrets exists"; exit 1 }

if (Test-Path -LiteralPath $file) {
  Copy-Item -LiteralPath $file "$file.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
  Write-Host "existing $Bot.env backed up"
}
@(
  "# telegram bot '$Bot' - written by setup-telegram.ps1 $(Get-Date -Format s)"
  "TELEGRAM_BOT_TOKEN=$Token"
  "# destinations live in the address books (.config\telegram\trading.env etc., from Bitwarden)"
  $(if ($ChatId) { "TELEGRAM_CHAT_ID=$ChatId" } else { "# TELEGRAM_CHAT_ID=" })
  "# legacy name kept until the GARCH launcher is re-pointed:"
  "TELEGRAM_RICKYASSIST_BOT_TOKEN=$Token"
) | Set-Content -LiteralPath $file -Encoding UTF8

# lock the file down to this user
icacls $file /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
$shown = if ($ChatId) { $ChatId } else { '<none - run --discover>' }
Write-Host "wrote $file (chat id: $shown)"

$py = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "C:\Program Files\Python312\python.exe" }
if ($ChatId) {
  & $py -m common.alerts.telegram --bot $Bot --test
} else {
  Write-Host "Send the bot a message (or add it to the group and post), then:"
  Write-Host "  $py -m common.alerts.telegram --bot $Bot --discover"
  Write-Host "and put the chat id into $file as TELEGRAM_CHAT_ID."
}
