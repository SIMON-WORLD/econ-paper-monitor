param(
  [string]$TaskName = "Econ Papers Daily - Local CNKI Supplement",
  [string[]]$Times = @("00:10", "06:10", "12:10", "18:10"),
  [switch]$NoPush,
  [string]$RunnerPath = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
# PowerShell 7 uses the same OpenSSL/TLS stack as the verified local Git path.
# Keep Windows PowerShell as a fallback for machines without pwsh installed.
$shell = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
if ([string]::IsNullOrWhiteSpace($shell)) {
  $shell = (Get-Command powershell.exe -ErrorAction Stop).Source
}
if ([string]::IsNullOrWhiteSpace($RunnerPath)) {
  $RunnerPath = Join-Path $env:LOCALAPPDATA "AcademicDoor\econ-paper-monitor-cnki-runner"
}
$bootstrap = Join-Path $repo "scripts\bootstrap_local_cnki_runner.ps1"
& $shell -NoProfile -ExecutionPolicy Bypass -File $bootstrap -RunnerPath $RunnerPath
$bootstrapCode = $LASTEXITCODE
if ($bootstrapCode -ne 0) {
  throw "CNKI runner bootstrap failed with exit code $bootstrapCode"
}
$runner = Join-Path $RunnerPath "scripts\run_local_cnki_update.ps1"

if (-not (Test-Path -LiteralPath $runner)) {
  throw "Runner script not found: $runner"
}

$argumentParts = @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-WindowStyle", "Hidden",
  "-File", "`"$runner`""
)
if ($NoPush) {
  $argumentParts += "-NoPush"
}

$action = New-ScheduledTaskAction -Execute $shell -Argument ($argumentParts -join " ") -WorkingDirectory $RunnerPath
$triggers = foreach ($time in $Times) {
  New-ScheduledTaskTrigger -Daily -At $time
}
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 45)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $triggers `
  -Settings $settings `
  -Description "Fetch CNKI RSS locally, update Econ Papers Daily, and push generated site data." `
  -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Schedule: daily at $($Times -join ', ') (local time)"
Write-Host "Runner: $runner"
Write-Host "Log: $(Join-Path $RunnerPath 'local_admin\logs\local-cnki-update.log')"
