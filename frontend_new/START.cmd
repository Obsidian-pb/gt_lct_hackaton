@echo off
rem ============================================================================
rem  Тренажёр оператора ДДС «Система-112» — локальный запуск всего стенда
rem  Порядок запуска (plan3): 1) ai_service (8890) -> 2) backend_new (8000) ->
rem                            3) frontend_new (8080)
rem  1) запускает ИИ-микросервис (ai_service\START_AI.cmd)
rem  2) применяет миграции Alembic к БД system112_trainer
rem  3) запускает бэкенд (uvicorn) на http://127.0.0.1:8000
rem  4) запускает статический фронтенд на http://127.0.0.1:8080
rem  5) открывает страницу входа в браузере
rem  Остановка: STOP.cmd
rem  Для реальной генерации ИИ заполните AI_API_KEY в ai_service\.env
rem  (скрипт ai_service\SETUP_ENV.cmd создаст .env с AI_SERVICE_TOKEN).
rem ============================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "BACKEND_DIR=%~dp0..\backend_new"
set "PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [ОШИБКА] Python-окружение не найдено: %PYTHON%
    echo Создайте его один раз:
    echo   cd backend_new
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -e ".[dev]"
    pause
    exit /b 1
)

echo [1/5] Останавливаю ранее запущенные экземпляры...
call "%~dp0STOP.cmd" >nul 2>&1

echo [2/5] Запускаю ИИ-микросервис (ai_service, порт 8890)...
call "%~dp0..\ai_service\START_AI.cmd"

echo [3/5] Применяю миграции к БД system112_trainer...
cd /d "%BACKEND_DIR%"
"%PYTHON%" -m alembic upgrade head
if errorlevel 1 (
    echo [ОШИБКА] Миграции не применены. Убедитесь, что PostgreSQL запущен
    echo и строка DATABASE_URL в backend_new\.env корректна (по умолчанию
    echo postgresql+asyncpg://postgres:admin@localhost:5432/system112_trainer^).
    pause
    exit /b 1
)

echo [4/5] Запускаю бэкенд (порт 8000) и фронтенд (порт 8080)...
powershell -NoProfile -Command ^
  "$p = Start-Process -FilePath '%PYTHON%' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory '%BACKEND_DIR%' -WindowStyle Hidden -PassThru -RedirectStandardOutput '%BACKEND_DIR%\uvicorn.log' -RedirectStandardError '%BACKEND_DIR%\uvicorn.err.log'; $p.Id | Out-File -Encoding ascii '%BACKEND_DIR%\.backend.pid'"

powershell -NoProfile -Command ^
  "$p = Start-Process -FilePath '%PYTHON%' -ArgumentList '-m','http.server','8080' -WorkingDirectory '%~dp0' -WindowStyle Hidden -PassThru -RedirectStandardOutput '%~dp0http.log' -RedirectStandardError '%~dp0http.err.log'; $p.Id | Out-File -Encoding ascii '%~dp0\.frontend.pid'"

echo [5/5] Проверяю готовность API и ИИ-сервиса...
powershell -NoProfile -Command ^
  "$ok=$false; for($i=0;$i -lt 10;$i++){ try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 3; if($r.StatusCode -eq 200){$ok=$true;break} } catch { Start-Sleep -Milliseconds 700 } }; if($ok){ Write-Host 'API: OK (http://127.0.0.1:8000)' } else { Write-Host 'API: НЕ ОТВЕЧАЕТ. Смотрите backend_new\uvicorn.err.log' }"
powershell -NoProfile -Command ^
  "try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:8890/health' -UseBasicParsing -TimeoutSec 3; if($r.StatusCode -eq 200){ Write-Host 'AI-service: OK (http://127.0.0.1:8890)' } } catch { Write-Host 'AI-service: НЕ ОТВЕЧАЕТ. Смотрите ai_service\uvicorn.err.log' }"

start "" "http://127.0.0.1:8080/index.html"
echo.
echo Готово. Фронтенд: http://127.0.0.1:8080/index.html  (вход: admin / admin123)
echo API и Swagger: http://127.0.0.1:8000/docs
echo ИИ-микросервис: http://127.0.0.1:8890/api/docs
echo Остановка стенда: STOP.cmd
endlocal