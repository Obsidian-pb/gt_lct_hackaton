@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"

if not exist "%~dp0config.local.json" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0FIRST_RUN_KEY.ps1"
    if errorlevel 1 goto key_cancelled
)

call "%~dp0BUILD_UI.cmd"
if errorlevel 1 goto build_failed

if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" goto run_local314
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" goto run_local313
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" goto run_local312
where py >nul 2>nul
if not errorlevel 1 goto run_py
where python >nul 2>nul
if not errorlevel 1 goto run_python

echo Python 3 was not found. Run START.cmd to use the guided installer.
pause
exit /b 1

:run_local314
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" web_ui.py
goto done
:run_local313
"%LOCALAPPDATA%\Programs\Python\Python313\python.exe" web_ui.py
goto done
:run_local312
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" web_ui.py
goto done
:run_py
py -3 web_ui.py
goto done
:run_python
python web_ui.py
goto done
:key_cancelled
echo AI key setup was cancelled.
goto done
:build_failed
echo UI build failed.
:done
endlocal
pause
