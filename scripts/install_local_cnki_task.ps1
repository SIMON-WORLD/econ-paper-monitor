param(
  [string]$TaskName = "Econ Papers Daily - Local CNKI Supplement",
  [string]$Time = "12:10",
  [switch]$NoPush
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runner = Join-Path $repo "scripts\run_local_cnki_update.ps1"

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

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($argumentParts -join " ") -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 45)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Fetch CNKI RSS locally, update Econ Papers Daily, and push generated site data." `
  -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Schedule: daily at $Time"
Write-Host "Runner: $runner"
Write-Host "Log: $(Join-Path $repo 'local_admin\logs\local-cnki-update.log')"
