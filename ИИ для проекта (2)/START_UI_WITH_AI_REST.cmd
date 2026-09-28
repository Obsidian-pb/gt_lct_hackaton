@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not defined AI_REST_TOKEN (
    echo Set AI_REST_TOKEN first. It must match the dedicated AI REST server.
    pause
    exit /b 1
)
if not defined AI_DIALOGUE_REST_URL set "AI_DIALOGUE_REST_URL=http://127.0.0.1:8890"
echo Dialogue AI REST: %AI_DIALOGUE_REST_URL%
call "%~dp0START.cmd"
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
