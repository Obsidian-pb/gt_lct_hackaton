@echo off
rem ============================================================================
rem  ai_service: однократная настройка окружения ИИ-микросервиса
rem  1) создаёт ai_service\.env из .env.example с AI_SERVICE_TOKEN (если нет)
rem  2) добавляет AI_SERVICE_URL / AI_SERVICE_TOKEN в backend_new\.env (если нет)
rem  Файлы .env не редактируются инструментами разработчика — только этим скриптом.
rem  После запуска заполните AI_API_KEY (и AI_BASE_URL / AI_MODEL) в ai_service\.env.
rem ============================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "BACKEND_DIR=%~dp0..\backend_new"
set "TOKEN=a6893179641941f3a45c8639767ca814857c99c8da164f12b4818cb924745cd4"

rem --- 1) ai_service\.env ----------------------------------------------------
if exist ".env" (
    echo [1/2] ai_service\.env уже существует - оставляем как есть.
) else (
    copy ".env.example" ".env" >nul
    powershell -NoProfile -Command ^
      "$p='.env'; $c=Get-Content -LiteralPath $p -Raw; $c=$c -replace 'AI_SERVICE_TOKEN=.*', 'AI_SERVICE_TOKEN=%TOKEN%'; Set-Content -LiteralPath $p -Value $c -Encoding utf8"
    echo [1/2] Создан ai_service\.env с AI_SERVICE_TOKEN=%TOKEN%
)

rem --- 2) backend_new\.env ---------------------------------------------------
if exist "%BACKEND_DIR%\.env" (
    findstr /C:"AI_SERVICE_TOKEN=" "%BACKEND_DIR%\.env" >nul
    if errorlevel 1 (
        >>"%BACKEND_DIR%\.env" echo.
        >>"%BACKEND_DIR%\.env" echo # ИИ-микросервис (plans/plan3_ai_microservice.md): URL и токен доступа
        >>"%BACKEND_DIR%\.env" echo AI_SERVICE_URL=http://127.0.0.1:8890
        >>"%BACKEND_DIR%\.env" echo AI_SERVICE_TOKEN=%TOKEN%
        echo [2/2] В backend_new\.env добавлены AI_SERVICE_URL и AI_SERVICE_TOKEN
    ) else (
        echo [2/2] backend_new\.env уже содержит AI_SERVICE_TOKEN - пропущено
    )
) else (
    echo [2/2] backend_new\.env не найден. Скопируйте .env.example в backend_new\.env
    echo        и добавьте строки:
    echo        AI_SERVICE_URL=http://127.0.0.1:8890
    echo        AI_SERVICE_TOKEN=%TOKEN%
)

echo.
echo ВАЖНО: заполните ключ провайдера в ai_service\.env (AI_API_KEY) и,
echo при необходимости, AI_BASE_URL и AI_MODEL. Затем запустите START_AI.cmd.
echo Порядок запуска всего стенда: ai_service -^> backend_new -^> frontend_new.
endlocal