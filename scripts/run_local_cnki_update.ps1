param(
  [switch]$NoPush,
  [int]$MaxAgeDays = 90
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$logDir = Join-Path $repo "local_admin\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "local-cnki-scheduled-task.log"

Set-Location $repo

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
