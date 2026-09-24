@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "PG=%ROOT%\runtime\pgsql\bin"
set "PY=%ROOT%\runtime\python\python.exe"
set "PGDATA=%ROOT%\data\pgdata"
set "PGPORT=5433"
if exist "%ROOT%\settings.cmd" call "%ROOT%\settings.cmd"

rem Копия на конец работы — пока база ещё запущена.
"%PG%\pg_ctl.exe" -D "%PGDATA%" status >nul 2>&1
if not errorlevel 1 (
  echo  Снимаю резервную копию базы...
  "%PY%" "%ROOT%\runtime\backup.py" "%PG%" %PGPORT% "%ROOT%\data\backups" >>"%ROOT%\data\logs\backup.log" 2>&1
)

echo  Останавливаю сервер...
taskkill /F /FI "WINDOWTITLE eq DDS112 server*" >nul 2>&1
echo  Останавливаю языковую модель...
taskkill /F /FI "WINDOWTITLE eq DDS112 model*" >nul 2>&1
taskkill /F /IM llama-server.exe >nul 2>&1
echo  Останавливаю PostgreSQL...
"%PG%\pg_ctl.exe" -D "%PGDATA%" -m fast -w stop >nul 2>&1
echo  Готово. Данные сохранены в data\.
timeout /t 3 >nul
exit /b 0
