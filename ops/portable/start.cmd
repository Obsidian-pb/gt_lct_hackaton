@echo off
setlocal
chcp 65001 >nul
title Тренажёр Системы-112
cd /d "%~dp0"
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"

rem ---------------------------------------------------------------------------
rem Переносной комплект: PostgreSQL, языковая модель и приложение запускаются
rem из этой папки, ничего не устанавливая в систему. Все данные — в data\.
rem Настройки, которые можно менять, — в settings.cmd рядом с этим файлом.
rem ---------------------------------------------------------------------------

set "PG=%ROOT%\runtime\pgsql\bin"
set "PY=%ROOT%\runtime\python\python.exe"
set "LLAMA=%ROOT%\runtime\llama\llama-server.exe"
set "PGDATA=%ROOT%\data\pgdata"
set "LOGS=%ROOT%\data\logs"
set "PGPORT=5433"
set "WEB_PORT=8090"
rem 127.0.0.1 — только этот компьютер. 0.0.0.0 — доступ ученикам из класса
rem по адресу компьютера в сети; база и модель наружу не открываются.
set "WEB_HOST=127.0.0.1"
set "LLM_PORT=8081"
set "LLM_THREADS=%NUMBER_OF_PROCESSORS%"
if exist "%ROOT%\settings.cmd" call "%ROOT%\settings.cmd"

if not exist "%LOGS%" mkdir "%LOGS%"
if not exist "%ROOT%\data\backups" mkdir "%ROOT%\data\backups"

rem PostgreSQL отказывается работать с правами администратора — это его
rem защита, а не наша прихоть. Запускать нужно обычным двойным щелчком.
net session >nul 2>&1
if %errorlevel%==0 (
  echo.
  echo  Окно открыто от имени администратора. PostgreSQL так не запускается.
  echo  Закройте его и запустите start.cmd обычным двойным щелчком.
  echo.
  pause
  exit /b 1
)

rem Запросы к 127.0.0.1 не должны уходить в прокси организации.
set "NO_PROXY=127.0.0.1,localhost"
set "no_proxy=127.0.0.1,localhost"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%ROOT%\app\backend"

echo.
echo  === Тренажёр операторов и диспетчеров Системы-112 ===
echo.

rem --- База данных -----------------------------------------------------------
if not exist "%PGDATA%\PG_VERSION" (
  echo  Первый запуск: создаю базу данных...
  set "FIRST_RUN=1"
  "%PG%\initdb.exe" -D "%PGDATA%" -U trainer -A trust -E UTF8 --locale=C >"%LOGS%\initdb.log" 2>&1
  if errorlevel 1 (
    echo  Не удалось создать базу. Подробности: data\logs\initdb.log
    pause
    exit /b 1
  )
)
"%PG%\pg_ctl.exe" -D "%PGDATA%" status >nul 2>&1
if errorlevel 1 (
  echo  Запускаю PostgreSQL на порту %PGPORT%...
  "%PG%\pg_ctl.exe" -D "%PGDATA%" -l "%LOGS%\postgres.log" -o "-p %PGPORT% -c listen_addresses=127.0.0.1" -w start >nul
  if errorlevel 1 (
    echo  PostgreSQL не запустился. Подробности: data\logs\postgres.log
    pause
    exit /b 1
  )
)
"%PG%\psql.exe" -p %PGPORT% -U trainer -d postgres -tAc "select 1 from pg_database where datname='trainer'" 2>nul | findstr /x 1 >nul
if errorlevel 1 "%PG%\createdb.exe" -p %PGPORT% -U trainer trainer

rem --- Ключ подписи токенов: создаётся один раз и хранится в data\ ----------
if not exist "%ROOT%\data\secret.txt" (
  "%PY%" -c "import secrets,pathlib;pathlib.Path(r'%ROOT%\data\secret.txt').write_text(secrets.token_hex(32))"
)
set /p SECRET_KEY=<"%ROOT%\data\secret.txt"

rem --- Языковая модель -------------------------------------------------------
set "MODEL="
for %%f in ("%ROOT%\models\*.gguf") do set "MODEL=%%~ff"
if defined MODEL (
  echo  Запускаю языковую модель: %MODEL:~-45%
  set "LLAMA_ARG_MODEL=%MODEL%"
  set "LLAMA_ARG_ALIAS=qwen"
  set "LLAMA_ARG_HOST=127.0.0.1"
  set "LLAMA_ARG_PORT=%LLM_PORT%"
  set "LLAMA_ARG_CTX_SIZE=8192"
  set "LLAMA_ARG_N_PARALLEL=2"
  set "LLAMA_ARG_FLASH_ATTN=on"
  set "LLAMA_ARG_THREADS=%LLM_THREADS%"
  start "DDS112 model" /min "%LLAMA%" --log-file "%LOGS%\llm.log"
  set "LLM_PROVIDER=local"
  set "LLM_BASE_URL=http://127.0.0.1:%LLM_PORT%/v1"
  set "LLM_MODEL=qwen"
  set "LLM_DISABLE_THINKING=true"
  set "LLM_TIMEOUT_SECONDS=180"
) else (
  echo  Файла модели в папке models\ нет — разбор от нейросети будет отключён.
  set "LLM_PROVIDER=stub"
)

rem --- Приложение ------------------------------------------------------------
set "DATABASE_URL=postgresql+psycopg://trainer@127.0.0.1:%PGPORT%/trainer"
set "STATIC_DIR=%ROOT%\app\web"
set "BACKUP_DIR=%ROOT%\data\backups"
cd /d "%ROOT%\app\backend"
rem Копия перед обновлением схемы: если миграция что-то испортит, есть
rem к чему откатиться. При первом запуске копировать ещё нечего.
if not defined FIRST_RUN (
  echo  Снимаю резервную копию базы...
  "%PY%" "%ROOT%\runtime\backup.py" "%PG%" %PGPORT% "%ROOT%\data\backups" >>"%LOGS%\backup.log" 2>&1
)
echo  Обновляю схему базы и учебные данные...
"%PY%" scripts\migrate.py >>"%LOGS%\setup.log" 2>&1 || goto :setup_failed
"%PY%" scripts\seed.py >>"%LOGS%\setup.log" 2>&1 || goto :setup_failed
"%PY%" scripts\import_tickets.py >>"%LOGS%\setup.log" 2>&1 || goto :setup_failed
"%PY%" scripts\import_tickets.py --refresh-callers >>"%LOGS%\setup.log" 2>&1

echo  Запускаю сервер на порту %WEB_PORT%...
start "DDS112 server" /min "%PY%" -m uvicorn app.main:app --host %WEB_HOST% --port %WEB_PORT%
"%PY%" "%ROOT%\runtime\wait_health.py" %WEB_PORT% 90
if errorlevel 1 (
  echo  Сервер не ответил за 90 секунд. Смотрите окно «DDS112 server».
  pause
  exit /b 1
)

start http://127.0.0.1:%WEB_PORT%/
echo.
echo  Готово: http://127.0.0.1:%WEB_PORT%/
if "%WEB_HOST%"=="0.0.0.0" (
  echo.
  echo  Доступ из класса открыт. Адреса для учеников:
  "%PY%" "%ROOT%\runtime\lan_addresses.py" %WEB_PORT%
  echo  Если Windows спросит про брандмауэр — разрешите доступ в частных сетях,
  echo  иначе ученики не подключатся. Для этого нужны права администратора.
)
echo  Учётные записи: admin, teacher, student, student2 — пароль совпадает с логином.
echo  Модель загружается в память ещё 1–3 минуты; до этого разбор придёт с задержкой.
echo.
echo  Это окно можно закрыть. Остановка — stop.cmd.
echo.
pause
exit /b 0

:setup_failed
echo  Подготовка базы не удалась. Подробности: data\logs\setup.log
pause
exit /b 1
