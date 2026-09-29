@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0SETUP_SHARED_SERVER_NO_DOCKER.ps1"
if errorlevel 1 pause
