$ErrorActionPreference = "Stop"

$Repo = "academic-door/econ-paper-monitor"
# Resolve gh from PATH (no hardcoded install path); allow override via $env:GH_EXE.
$Gh = if ($env:GH_EXE) { $env:GH_EXE } else { (Get-Command gh -ErrorAction SilentlyContinue).Source }
if ([string]::IsNullOrWhiteSpace($Gh)) { $Gh = "gh" }

# Repo root = parent of this scripts dir, so the trigger works from any checkout.
$WorkDir = Split-Path -Parent $PSScriptRoot

Set-Location -LiteralPath $WorkDir
& $Gh workflow run watchdog.yml --repo $Repo