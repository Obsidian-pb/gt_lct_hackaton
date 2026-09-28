@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0PREPARE_AI_CONNECTION.ps1"
endlocal
