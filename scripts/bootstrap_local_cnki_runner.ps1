param(
  [string]$RunnerPath = "",
  [string]$Remote = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ([string]::IsNullOrWhiteSpace($RunnerPath)) {
  $RunnerPath = Join-Path $env:LOCALAPPDATA "AcademicDoor\econ-paper-monitor-cnki-runner"
}
if ([string]::IsNullOrWhiteSpace($Remote)) {
  $Remote = (git -C $repo remote get-url origin).Trim()
}

$parent = Split-Path -Parent $RunnerPath
New-Item -ItemType Directory -Force -Path $parent | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $RunnerPath ".git"))) {
  if (Test-Path -LiteralPath $RunnerPath) {
    $children = @(Get-ChildItem -LiteralPath $RunnerPath -Force)
    if ($children.Count -gt 0) {
      throw "RunnerPath exists and is not an empty Git checkout: $RunnerPath"
    }
  }
  git clone --branch main --single-branch $Remote $RunnerPath
} else {
  $branch = (git -C $RunnerPath branch --show-current).Trim()
  if ($branch -ne "main") {
    throw "CNKI runner must use branch main, found '$branch'"
  }
  $dirty = git -C $RunnerPath status --porcelain
  if ($dirty) {
    throw "CNKI runner has uncommitted changes; inspect it before scheduling: $RunnerPath"
  }
  git -C $RunnerPath -c http.sslbackend=openssl pull --ff-only origin main
}

Write-Host "CNKI runner ready: $RunnerPath"
