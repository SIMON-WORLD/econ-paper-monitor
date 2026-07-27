param(
  [string]$TaskName = "Econ Papers Daily - Local CNKI Supplement",
  [string[]]$Times = @("00:10", "06:10", "12:10", "18:10"),
  [switch]$NoPush,
  [string]$RunnerPath = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ([string]::IsNullOrWhiteSpace($RunnerPath)) {
  $RunnerPath = $repo
}
$runner = Join-Path $RunnerPath "scripts\run_local_cnki_update.ps1"

# PowerShell 7 uses the same OpenSSL/TLS stack as the verified local Git path.
# Keep Windows PowerShell as a fallback for machines without pwsh installed.
$shell = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
if ([string]::IsNullOrWhiteSpace($shell)) {
  $shell = (Get-Command powershell.exe -ErrorAction Stop).Source
}

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

$action = New-ScheduledTaskAction -Execute $shell -Argument ($argumentParts -join " ") -WorkingDirectory $repo
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
Write-Host "Log: $(Join-Path $repo 'local_admin\logs\local-cnki-update.log')"
