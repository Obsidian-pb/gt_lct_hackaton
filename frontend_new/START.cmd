@echo off
rem ============================================================================
rem  Тренажёр оператора ДДС «Система-112» — локальный запуск всего стенда
rem  1) применяет миграции Alembic к БД system112_trainer
rem  2) запускает бэкенд (uvicorn) на http://127.0.0.1:8000
rem  3) запускает статический фронтенд на http://127.0.0.1:8080
rem  4) открывает страницу входа в браузере
rem  Остановка: STOP.cmd
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

echo [1/4] Останавливаю ранее запущенные экземпляры...
call "%~dp0STOP.cmd" >nul 2>&1

echo [2/4] Применяю миграции к БД system112_trainer...
cd /d "%BACKEND_DIR%"
"%PYTHON%" -m alembic upgrade head
if errorlevel 1 (
    echo [ОШИБКА] Миграции не применены. Убедитесь, что PostgreSQL запущен
    echo и строка DATABASE_URL в backend_new\.env корректна (по умолчанию
    echo postgresql+asyncpg://postgres:admin@localhost:5432/system112_trainer^).
    pause
    exit /b 1
)

echo [3/4] Запускаю бэкенд (порт 8000) и фронтенд (порт 8080)...
powershell -NoProfile -Command ^
  "$p = Start-Process -FilePath '%PYTHON%' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory '%BACKEND_DIR%' -WindowStyle Hidden -PassThru -RedirectStandardOutput '%BACKEND_DIR%\uvicorn.log' -RedirectStandardError '%BACKEND_DIR%\uvicorn.err.log'; $p.Id | Out-File -Encoding ascii '%BACKEND_DIR%\.backend.pid'"

powershell -NoProfile -Command ^
  "$p = Start-Process -FilePath '%PYTHON%' -ArgumentList '-m','http.server','8080' -WorkingDirectory '%~dp0' -WindowStyle Hidden -PassThru -RedirectStandardOutput '%~dp0http.log' -RedirectStandardError '%~dp0http.err.log'; $p.Id | Out-File -Encoding ascii '%~dp0\.frontend.pid'"

echo [4/4] Проверяю готовность API...
powershell -NoProfile -Command ^
  "$ok=$false; for($i=0;$i -lt 10;$i++){ try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 3; if($r.StatusCode -eq 200){$ok=$true;break} } catch { Start-Sleep -Milliseconds 700 } }; if($ok){ Write-Host 'API: OK (http://127.0.0.1:8000)' } else { Write-Host 'API: НЕ ОТВЕЧАЕТ. Смотрите backend_new\uvicorn.err.log' }"

start "" "http://127.0.0.1:8080/index.html"
echo.
echo Готово. Фронтенд: http://127.0.0.1:8080/index.html  (вход: admin / admin123)
echo API и Swagger: http://127.0.0.1:8000/docs
echo Остановка стенда: STOP.cmd
endlocal