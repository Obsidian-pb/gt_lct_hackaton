@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0FIRST_RUN_KEY.ps1" -Force
if errorlevel 1 (
    echo AI settings were not changed.
    pause
    exit /b 1
)
echo AI settings saved. Run RESTART.cmd if the application is already open.
pause
endlocal
