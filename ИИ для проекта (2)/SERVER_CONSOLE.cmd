@echo off
setlocal
title 112 - server console
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0SERVER_CONSOLE.ps1"
echo.
echo Server console stopped. Run START.cmd to start again.
endlocal
