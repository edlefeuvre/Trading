# sync-secrets.ps1 - Bitwarden is the master; this writes the runtime copies.
#
# For every Bitwarden folder named in -Providers (default: binance, telegram) and every
# item in it, write %USERPROFILE%\.config\<folder>\<item>.env containing the item's
# custom fields as KEY=value lines. Field names must look like env vars (UPPER_CASE);
# other fields (rotated, used_by, permissions, ...) are written as comments.
#
#   .\deploy\windows\sync-secrets.ps1            # write what changed, report names only
#   .\deploy\windows\sync-secrets.ps1 -WhatIf    # show what would change, write nothing
#   .\deploy\windows\sync-secrets.ps1 -Providers binance
#
# Never writes outside .config\<provider>\ . Never touches .config\telegram-webhook\ (Paperclip owns it).
# Never prints a value. Existing files are backed up once per run before being replaced.
[CmdletBinding(SupportsShouldProcess)]
param(
  [string[]]$Providers = @('binance','telegram'),
  [string]$ConfigRoot  = (Join-Path $env:USERPROFILE ".config")
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot "bw-common.ps1")

$forbidden = @('telegram-webhook','bitwarden')
$session = Open-BwSession
$changed = @(); $unchanged = @(); $skipped = @()
try {
  bw sync --session $session | Out-Null
  $folders = bw list folders --session $session | ConvertFrom-Json
  foreach ($prov in $Providers) {
    if ($forbidden -contains $prov) { Write-Warning "refusing provider '$prov'"; continue }
    $folder = $folders | Where-Object { $_.name -eq $prov } | Select -First 1
    if (-not $folder) { Write-Warning "no Bitwarden folder named '$prov'"; continue }
    $items = bw list items --folderid $folder.id --session $session | ConvertFrom-Json
    if (-not $items) { Write-Warning "folder '$prov' is empty"; continue }
    $dir = Join-Path $ConfigRoot $prov
    New-Item -ItemType Directory -Force -Path $dir -WhatIf:$false | Out-Null

    foreach ($it in $items) {
      $name = ($it.name -replace '[^A-Za-z0-9_.-]', '_')
      if (-not $it.fields) { $skipped += "$prov/$name (no custom fields)"; continue }
      $lines = @("# $prov/$name - written by sync-secrets.ps1 from Bitwarden, do not edit by hand")
      $envCount = 0
      foreach ($f in $it.fields) {
        if ($f.name -cmatch '^[A-Z][A-Z0-9_]*$') { $lines += "$($f.name)=$($f.value)"; $envCount++ }
        else                                    { $lines += "# $($f.name): $($f.value)" }
      }
      # legacy compatibility: the GARCH launcher reads this name
      if ($prov -eq 'telegram' -and $name -eq 'rickyassist_bot') {
        $tok = ($it.fields | Where-Object { $_.name -eq 'TELEGRAM_BOT_TOKEN' }).value
        if ($tok) { $lines += "TELEGRAM_RICKYASSIST_BOT_TOKEN=$tok" }
      }
      if ($envCount -eq 0) { $skipped += "$prov/$name (no UPPER_CASE fields)"; continue }

      $file = Join-Path $dir "$name.env"
      $new  = ($lines -join "`r`n") + "`r`n"
      $old  = if (Test-Path -LiteralPath $file) { Get-Content -LiteralPath $file -Raw } else { "" }
      # compare ignoring the header timestamp line
      $strip = { param($t) ($t -split "`r?`n" | Where-Object { $_ -notmatch '^# .* written by sync-secrets' }) -join "`n" }
      if ((& $strip $old) -eq (& $strip $new)) { $unchanged += "$prov/$name"; continue }

      if ($PSCmdlet.ShouldProcess($file, "write")) {
        if ($old) { Copy-Item -LiteralPath $file "$file.bak" -Force }
        [System.IO.File]::WriteAllText($file, $new, (New-Object System.Text.UTF8Encoding($false)))
        icacls $file /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
      }
      $changed += "$prov/$name"
    }
  }
} finally {
  bw lock --session $session | Out-Null
}
"changed   : " + ($(if ($changed)   { $changed   -join ', ' } else { '-' }))
"unchanged : " + ($(if ($unchanged) { $unchanged -join ', ' } else { '-' }))
if ($skipped) { "skipped   : " + ($skipped -join ', ') }
if ($changed -and -not $WhatIfPreference) {
  Write-Host "restart anything that read a changed file (e.g. TS01-runner) so it picks the new values up."
}
