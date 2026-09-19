@echo off
chcp 65001 >nul
set PYTHONUTF8=1
pushd "%~dp0"
set "AI_PYTHONW=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if exist "%AI_PYTHONW%" (
  start "" "%AI_PYTHONW%" web_ui.py
) else (
  start "" pyw -3 web_ui.py
)
popd
