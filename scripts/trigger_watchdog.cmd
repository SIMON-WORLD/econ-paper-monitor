@echo off
setlocal
rem Repo root = parent of this scripts dir, so the trigger works from any checkout.
cd /d "%~dp0.."
gh workflow run watchdog.yml --repo academic-door/econ-paper-monitor