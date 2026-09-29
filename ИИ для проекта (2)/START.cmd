@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
<<<<<<< HEAD

rem Use the shared PostgreSQL server after setup has created .env.server.
if exist "%~dp0.env.server" goto shared

=======
>>>>>>> ec5491b6745f1dd11607901b6ecc81befa475fae
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_ALL.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo Launch failed. See .runtime\launcher-error.log and service logs.
    pause
)
endlocal & exit /b %RC%
<<<<<<< HEAD

:shared
echo [112] Server configuration found. Starting shared PostgreSQL mode...
call "%~dp0START_SHARED_SERVER.cmd"
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
=======
>>>>>>> ec5491b6745f1dd11607901b6ecc81befa475fae
