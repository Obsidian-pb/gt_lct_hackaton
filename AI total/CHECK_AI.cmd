@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0PREPARE_AI_CONNECTION.ps1"
where py >nul 2>nul
if not errorlevel 1 goto use_py
where python >nul 2>nul
if not errorlevel 1 goto use_python
echo Python 3 was not found. Run START.cmd first.
pause
exit /b 1
:use_py
py -3 check_ai.py
goto done
:use_python
python check_ai.py
:done
set "RC=%ERRORLEVEL%"
echo.
pause
endlocal & exit /b %RC%
