# setup-bitwarden.ps1 - one-time: install the Bitwarden CLI, store the unlock material
# for this Windows user (DPAPI-encrypted), and prove that login/unlock/sync work.
#
#   .\deploy\windows\setup-bitwarden.ps1
#
# You will be asked for three things, none of which are echoed or stored in plain text:
#   - API client_id and client_secret   (web vault > Settings > Security > Keys > View API key)
#   - master password
# They are saved with Export-Clixml, which encrypts SecureStrings with Windows DPAPI:
# readable only by THIS user on THIS machine. File: %USERPROFILE%\.config\bitwarden\unlock.xml
param([switch]$Reconfigure)
$ErrorActionPreference = 'Stop'
$cfgDir  = Join-Path $env:USERPROFILE ".config\bitwarden"
$cfgFile = Join-Path $cfgDir "unlock.xml"
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null

# 1. CLI present?
if (-not (Get-Command bw -ErrorAction SilentlyContinue)) {
  Write-Host "Bitwarden CLI not found. Installing with winget..."
  winget install --id Bitwarden.CLI -e --accept-source-agreements --accept-package-agreements
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
  if (-not (Get-Command bw -ErrorAction SilentlyContinue)) {
    Write-Error "bw still not on PATH. Install manually (winget install Bitwarden.CLI, or npm i -g @bitwarden/cli) and re-run."
    exit 1
  }
}
Write-Host ("bw version " + (bw --version))

# 2. Unlock material
if ((Test-Path -LiteralPath $cfgFile) -and -not $Reconfigure) {
  Write-Host "unlock.xml already present (use -Reconfigure to replace)"
} else {
  $clientId     = Read-Host -Prompt "Bitwarden API client_id"        -AsSecureString
  $clientSecret = Read-Host -Prompt "Bitwarden API client_secret"    -AsSecureString
  $master       = Read-Host -Prompt "Bitwarden master password"      -AsSecureString
  [pscustomobject]@{ ClientId=$clientId; ClientSecret=$clientSecret; Master=$master } | Export-Clixml -LiteralPath $cfgFile
  icacls $cfgFile /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
  Write-Host "saved $cfgFile (DPAPI, this user only)"
}

# 3. Prove it works, using the shared helper
. (Join-Path $PSScriptRoot "bw-common.ps1")
$session = Open-BwSession -ConfigFile $cfgFile
try {
  bw sync --session $session | Out-Null
  $folders = bw list folders --session $session | ConvertFrom-Json
  Write-Host "login/unlock/sync OK. Folders in vault:"
  $folders | Where-Object { $_.name } | ForEach-Object {
    $n = (bw list items --folderid $_.id --session $session | ConvertFrom-Json).Count
    "  {0,-20} {1} item(s)" -f $_.name, $n
  }
  Write-Host "Expected for the trading setup: folders 'binance' and 'telegram' (lower-case), one item per key/bot."
} finally {
  bw lock --session $session | Out-Null
}
