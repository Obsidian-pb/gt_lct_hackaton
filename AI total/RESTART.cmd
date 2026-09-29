@echo off
setlocal
cd /d "%~dp0"
call "%~dp0STOP.cmd"
call "%~dp0START.cmd"
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
