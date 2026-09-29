@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 goto use_py
where python >nul 2>nul
if not errorlevel 1 goto use_python
echo Python 3 was not found. Run START.cmd first.
pause
exit /b 1
:use_py
py -3 init_storage.py --init --self-test --check --pause
goto done
:use_python
python init_storage.py --init --self-test --check --pause
:done
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%