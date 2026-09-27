@echo off
rem ============================================================================
rem  Тренажёр оператора ДДС «Система-112» — остановка локального стенда
rem  Останавливает:
rem   - бэкенд (uvicorn app.main:app, порт 8000)
rem   - статический фронтенд (http.server 8080)
rem  Поиск процессов: PID-файлы (.backend.pid / .frontend.pid), затем фильтр
rem  по командной строке процесса. Чужие процессы не затрагиваются.
rem ============================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "BACKEND_DIR=%~dp0..\backend_new"

echo Останавливаю процессы тренажёра...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ids = @();" ^
  "foreach ($f in @('%BACKEND_DIR%\.backend.pid', '%~dp0.frontend.pid')) {" ^
  "  if (Test-Path -LiteralPath $f) { $id = [int](Get-Content -LiteralPath $f -Raw); $ids += $id; Remove-Item -LiteralPath $f -Force }" ^
  "};" ^
  "$procs = Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'app\.main:app') -or $_.CommandLine -match 'http\.server 8080' };" ^
  "foreach ($p in $procs) { $ids += $p.ProcessId };" ^
  "$ids = $ids | Select-Object -Unique;" ^
  "if ($ids.Count -eq 0) { Write-Host '  Работающих процессов не найдено.' } else {" ^
  "  foreach ($id in $ids) { try { Stop-Process -Id $id -Force -ErrorAction Stop; Write-Host ('  Остановлен PID ' + $id) } catch {} }" ^
  "}"

echo Готово. Порты 8000 и 8080 свободны.
endlocal