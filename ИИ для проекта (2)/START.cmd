@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"

rem First launch: always require the recipient's own AI key.
if not exist "%~dp0config.local.json" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0FIRST_RUN_KEY.ps1"
    if errorlevel 1 goto key_cancelled
)

call "%~dp0BUILD_UI.cmd"
if errorlevel 1 goto build_failed

goto find_python

:find_python
if exist "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe" goto run_local314
if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" goto run_local313
if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" goto run_local312
where pyw >nul 2>nul
if not errorlevel 1 goto run_pyw
where pythonw >nul 2>nul
if not errorlevel 1 goto run_pythonw
where py >nul 2>nul
if not errorlevel 1 goto run_py
where python >nul 2>nul
if not errorlevel 1 goto run_python

goto offer_python

:offer_python
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_PYTHON.ps1"
if errorlevel 1 goto python_missing
if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" goto run_local312
where pyw >nul 2>nul
if not errorlevel 1 goto run_pyw
where pythonw >nul 2>nul
if not errorlevel 1 goto run_pythonw
where py >nul 2>nul
if not errorlevel 1 goto run_py
where python >nul 2>nul
if not errorlevel 1 goto run_python
goto python_missing

:run_local314
start "" "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe" web_ui.py
goto done
:run_local313
start "" "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" web_ui.py
goto done
:run_local312
start "" "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" web_ui.py
goto done
:run_pyw
start "" pyw -3 web_ui.py
goto done
:run_pythonw
start "" pythonw web_ui.py
goto done
:run_py
start "" py -3 web_ui.py
goto done
:run_python
start "" python web_ui.py
goto done

:key_cancelled
echo AI key setup was cancelled. Nothing was started.
pause
exit /b 1
:python_missing
echo Python 3 was not found. Install Python 3 and run START.cmd again.
pause
exit /b 1
:build_failed
echo UI build failed. Run START_CONSOLE.cmd for diagnostics.
pause
exit /b 1
:done
endlocal
exit /b 0
