@echo off
setlocal
cd /d E:\BaiduSyncdisk\Work\Agent_automation\vibe_coding\econ-paper-monitor
"D:\Software\GitHub CLI\gh.exe" workflow run watchdog.yml --repo academic-door/econ-paper-monitor
