$ErrorActionPreference = "Stop"

$Repo = "SIMON-WORLD/econ-paper-monitor"
$Gh = "D:\Software\GitHub CLI\gh.exe"
$WorkDir = "E:\BaiduSyncdisk\Work\Agent_automation\vibe_coding\econ-paper-monitor"

Set-Location -LiteralPath $WorkDir
& $Gh workflow run watchdog.yml --repo $Repo
