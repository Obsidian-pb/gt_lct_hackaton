@echo off
chcp 65001 >nul
set PYTHONUTF8=1
pushd "%~dp0"
set "AI_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%AI_PYTHON%" (
  "%AI_PYTHON%" console.py
) else (
  py -3 console.py
)
popd
pause
