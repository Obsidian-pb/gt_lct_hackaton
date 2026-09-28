@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not defined AI_REST_TOKEN (
    echo Set AI_REST_TOKEN first. See AI_REST_API.md.
    pause
    exit /b 1
)
where py >nul 2>nul
if not errorlevel 1 goto run_py
where python >nul 2>nul
if not errorlevel 1 goto run_python
echo Python 3 was not found.
pause
exit /b 1
:run_py
py -3 ai_rest_server.py %*
goto done
:run_python
python ai_rest_server.py %*
:done
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
