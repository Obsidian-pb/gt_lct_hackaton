@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0IMPORT_LEGACY_TO_POSTGRES.ps1"
if errorlevel 1 pause
