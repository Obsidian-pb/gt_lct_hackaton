@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "PG=%ROOT%\runtime\pgsql\bin"
set "PGDATA=%ROOT%\data\pgdata"

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
