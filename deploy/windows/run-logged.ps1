# run-logged.ps1 - run another script in this folder with a full transcript, and keep the window open.
#
#   .\deploy\windows\run-logged.ps1 setup-bitwarden.ps1
#   .\deploy\windows\run-logged.ps1 sync-secrets.ps1 -WhatIf
#
# Writes logs\<script>-<timestamp>.log under the repo root. Secrets typed at -AsSecureString
# prompts are never captured; the log is safe to share.
param(
  [Parameter(Mandatory=$true, Position=0)][string]$Script,
  [Parameter(ValueFromRemainingArguments=$true)][string[]]$Args
)
$repo = Split-Path (Split-Path $PSScriptRoot)
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir ("{0}-{1}.log" -f [IO.Path]::GetFileNameWithoutExtension($Script), $stamp)
$target = Join-Path $PSScriptRoot $Script
if (-not (Test-Path -LiteralPath $target)) { Write-Error "no such script: $target"; Read-Host "Enter to close"; exit 1 }

Start-Transcript -LiteralPath $log -Force | Out-Null
try {
  "== $Script $($Args -join ' ')"
  "== $(Get-Date -Format s)  PS $($PSVersionTable.PSVersion)  user $env:USERNAME  cwd $PWD"
  "== bw: $(if (Get-Command bw -ErrorAction SilentlyContinue) { (Get-Command bw).Source } else { 'not on PATH' })"
  "== python: $(if (Get-Command python -ErrorAction SilentlyContinue) { (Get-Command python).Source } else { 'not on PATH' })"
  ""
  $global:LASTEXITCODE = 0
  & $target @Args
  ""
  "== finished, exit code $LASTEXITCODE"
} catch {
  ""
  "== FAILED: $($_.Exception.GetType().Name): $($_.Exception.Message)"
  "== at: $($_.InvocationInfo.PositionMessage)"
  if ($_.ScriptStackTrace) { "== stack:"; $_.ScriptStackTrace }
} finally {
  Stop-Transcript | Out-Null
  # belt and braces: mask anything that looks like a long token before the log is shared
  (Get-Content -LiteralPath $log -Raw) -replace '([A-Za-z0-9_\-]{40,})', '<redacted-40+chars>' |
    Set-Content -LiteralPath $log -Encoding UTF8
  Write-Host ""
  Write-Host "log written to $log" -ForegroundColor Cyan
  Read-Host "Press Enter to close"
}
