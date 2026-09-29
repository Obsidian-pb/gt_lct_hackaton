@echo off
setlocal
cd /d "%~dp0"
title Trainer 112 - Shared Server
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_SHARED_SERVER.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [112] Startup failed. See .runtime\shared-startup.log
  pause
)
endlocal & exit /b %RC%
