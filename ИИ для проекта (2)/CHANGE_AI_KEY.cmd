@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0FIRST_RUN_KEY.ps1" -Force
if errorlevel 1 (
    echo Key was not changed.
    pause
    exit /b 1
)
echo Key updated. Restart the program if it is already open.
pause
endlocal
