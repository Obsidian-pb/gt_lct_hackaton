@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not defined AI_REST_TOKEN (
    echo Set AI_REST_TOKEN first. See AI_FRONTEND_REST_INTEGRATION.md.
    pause
    exit /b 1
)
call "%~dp0START_AI_REST.cmd" --host 0.0.0.0 %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
