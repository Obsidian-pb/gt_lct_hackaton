@echo off
rem ============================================================================
rem  ai_service: запуск ИИ-микросервиса (stateless REST, порт 8890)
rem  Порядок запуска всего стенда: ai_service -> backend_new -> frontend_new
rem  Остановка: frontend_new\STOP.cmd (останавливает и ИИ-микросервис)
rem ============================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

call "%~dp0SETUP_ENV.cmd"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [ОШИБКА] Python-окружение не найдено: %PYTHON%
    echo Создайте его один раз:
    echo   cd ai_service
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -e ".[dev]"
    pause
    exit /b 1
)

echo Запускаю ИИ-микросервис на http://127.0.0.1:8890 ...
powershell -NoProfile -Command ^
  "$p = Start-Process -FilePath '%PYTHON%' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8890' -WorkingDirectory '%~dp0' -WindowStyle Hidden -PassThru -RedirectStandardOutput '%~dp0uvicorn.log' -RedirectStandardError '%~dp0uvicorn.err.log'; $p.Id | Out-File -Encoding ascii '%~dp0.ai_service.pid'"

powershell -NoProfile -Command ^
  "$ok=$false; for($i=0;$i -lt 12;$i++){ try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:8890/health' -UseBasicParsing -TimeoutSec 3; if($r.StatusCode -eq 200){$ok=$true;break} } catch { Start-Sleep -Milliseconds 700 } }; if($ok){ Write-Host 'AI-service: OK (http://127.0.0.1:8890)' } else { Write-Host 'AI-service: НЕ ОТВЕЧАЕТ. Смотрите uvicorn.err.log'; exit 1 }"

echo Документация: http://127.0.0.1:8890/api/docs
echo Далее запустите backend_new (frontend_new\START.cmd).
endlocal