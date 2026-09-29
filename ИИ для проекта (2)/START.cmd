@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"

rem Use the shared PostgreSQL server after setup has created .env.server.
if exist "%~dp0.env.server" goto shared

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_ALL.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo Launch failed. See .runtime\launcher-error.log and service logs.
    pause
)
endlocal & exit /b %RC%

:shared
echo [112] Server configuration found. Starting shared PostgreSQL mode...
call "%~dp0START_SHARED_SERVER.cmd"
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
