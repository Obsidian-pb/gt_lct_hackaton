$ErrorActionPreference='Stop'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$envFile=Join-Path $root '.env.server'

$docker=Get-Command docker.exe -ErrorAction SilentlyContinue
if (-not $docker) {
    Write-Host '[112] Docker не найден. Перехожу к настройке PostgreSQL без Docker...' -ForegroundColor Yellow
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'SETUP_SHARED_SERVER_NO_DOCKER.ps1')
    exit $LASTEXITCODE
}

$password=Read-Host 'Придумайте пароль PostgreSQL (минимум 16 символов)'
if ($password.Length -lt 16) { throw 'Пароль слишком короткий.' }
if ($password.Contains('@') -or $password.Contains(':') -or $password.Contains('/') -or $password.Contains('#')) {
    throw 'Для простого DATABASE_URL не используйте в пароле символы @ : / #. Либо задайте URL-кодированный DATABASE_URL вручную.'
}
@"
TRAINER_DB_PASSWORD=$password
DATABASE_URL=postgresql://trainer112:$password@127.0.0.1:5432/trainer112
ALLOW_SELF_REGISTRATION=0
"@ | Set-Content -LiteralPath $envFile -Encoding UTF8
$env:TRAINER_DB_PASSWORD=$password
$env:DATABASE_URL="postgresql://trainer112:$password@127.0.0.1:5432/trainer112"

Write-Host '[112] Запуск PostgreSQL 16...' -ForegroundColor Cyan
& docker compose -f docker-compose.postgres.yml up -d
if ($LASTEXITCODE -ne 0) { throw 'Docker не смог запустить PostgreSQL.' }

$py=Get-Command py.exe -ErrorAction SilentlyContinue
if ($py) { $exe=$py.Source; $prefix=@('-3') } else { $p=Get-Command python.exe -ErrorAction Stop; $exe=$p.Source; $prefix=@() }
& $exe @prefix -m pip install -r requirements-server.txt --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить psycopg.' }

for($i=0;$i -lt 40;$i++) {
    & $exe @prefix manage_db.py status 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 1
}
& $exe @prefix manage_db.py migrate
if ($LASTEXITCODE -ne 0) { throw 'Не удалось применить миграции.' }

Write-Host ''
Write-Host 'PostgreSQL готов. Теперь создайте первого администратора:' -ForegroundColor Green
Write-Host '  py -3 manage_users.py create admin "Администратор" admin' -ForegroundColor Yellow
Write-Host 'После этого запускайте START_SHARED_SERVER.cmd.' -ForegroundColor Green
