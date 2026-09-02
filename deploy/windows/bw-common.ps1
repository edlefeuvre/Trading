# bw-common.ps1 - shared helper: turn the DPAPI-protected unlock.xml into a bw session key.
# Dot-source this; do not run it directly.
function ConvertFrom-Secure([securestring]$s) {
  $b = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
  try { [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) }
  finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}
function Open-BwSession {
  param([string]$ConfigFile = (Join-Path $env:USERPROFILE ".config\bitwarden\unlock.xml"))
  if (-not (Test-Path -LiteralPath $ConfigFile)) { throw "unlock.xml not found - run setup-bitwarden.ps1 first" }
  $c = Import-Clixml -LiteralPath $ConfigFile
  $env:BW_CLIENTID     = ConvertFrom-Secure $c.ClientId
  $env:BW_CLIENTSECRET = ConvertFrom-Secure $c.ClientSecret
  $env:BW_PASSWORD     = ConvertFrom-Secure $c.Master
  try {
    $status = (bw status | ConvertFrom-Json).status
    if ($status -eq 'unauthenticated') { bw login --apikey --quiet | Out-Null }
    $session = bw unlock --passwordenv BW_PASSWORD --raw
    if (-not $session) { throw "bw unlock failed" }
    return $session
  } finally {
    Remove-Item Env:BW_CLIENTID, Env:BW_CLIENTSECRET, Env:BW_PASSWORD -ErrorAction SilentlyContinue -WhatIf:$false
  }
}
