@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_ALL.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo Launch failed. See .runtime\launcher-error.log and service logs.
    pause
)
endlocal & exit /b %RC%
