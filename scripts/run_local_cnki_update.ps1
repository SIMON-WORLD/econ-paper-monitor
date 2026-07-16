param(
  [switch]$NoPush,
  [switch]$RunnerMode,
  [int]$MaxAgeDays = 90
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$logDir = Join-Path $repo "local_admin\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "local-cnki-scheduled-task.log"

Set-Location $repo

if ($RunnerMode) {
  $env:ECON_PAPER_MONITOR_RUNNER = "1"
  $previousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $fetchOutput = & git -C $repo fetch origin main 2>&1
  $fetchCode = $LASTEXITCODE
  $resetOutput = if ($fetchCode -eq 0) { & git -C $repo reset --hard origin/main 2>&1 }
  $resetCode = $LASTEXITCODE
  $ErrorActionPreference = $previousErrorActionPreference
  $fetchOutput | ForEach-Object {
    Add-Content -LiteralPath $log -Encoding UTF8 -Value $_
  }
  if ($fetchCode -ne 0) {
    throw "Unable to fetch academic-door/main for the local CNKI runner."
  }
  $resetOutput | ForEach-Object {
    Add-Content -LiteralPath $log -Encoding UTF8 -Value $_
  }
  if ($resetCode -ne 0) {
    throw "Unable to reset the local CNKI runner to origin/main."
  }
}

$argsList = @(".\scripts\local_cnki_update.py", "--max-age-days", "$MaxAgeDays")
if ($NoPush) {
  $argsList += "--no-push"
}

try {
  $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -LiteralPath $log -Encoding UTF8 -Value "[$stamp] scheduled task started"
  & python @argsList 2>&1 | ForEach-Object {
    Add-Content -LiteralPath $log -Encoding UTF8 -Value $_
  }
  $code = $LASTEXITCODE
  $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -LiteralPath $log -Encoding UTF8 -Value "[$stamp] scheduled task finished with exit code $code"
  exit $code
} catch {
  $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -LiteralPath $log -Encoding UTF8 -Value "[$stamp] scheduled task failed: $($_.Exception.Message)"
  exit 1
}
