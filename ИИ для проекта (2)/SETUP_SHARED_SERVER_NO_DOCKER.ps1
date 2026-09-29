$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$runtime=Join-Path $root '.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$envFile=Join-Path $root '.env.server'
$portableUrl='https://get.enterprisedb.com/postgresql/postgresql-16.15-1-windows-x64-binaries.zip'
$portableZip=Join-Path $runtime 'postgresql-16.15-1-windows-x64-binaries.zip'

function Find-PythonCommand {
    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($py) { return @{ Exe=$py.Source; Prefix=@('-3') } }
    $python=Get-Command python.exe -ErrorAction SilentlyContinue
    if($python) { return @{ Exe=$python.Source; Prefix=@() } }
    throw 'Python 3 не найден. Сначала установите Python 3.12+.'
}
function Invoke-Python([string[]]$CommandArgs) {
    if(-not $CommandArgs -or $CommandArgs.Count -eq 0) { throw 'Python: не передана команда.' }
    $cmd=Find-PythonCommand; $exe=$cmd.Exe; $prefix=@($cmd.Prefix)
    $previous=$ErrorActionPreference
    try {
        $ErrorActionPreference='Continue'
        & $exe @prefix @CommandArgs
        $code=$LASTEXITCODE
    } finally { $ErrorActionPreference=$previous }
    if($code -ne 0) { throw "Python command failed (exit $code): $($CommandArgs -join ' ')" }
}
function New-AppPassword {
    $bytes=New-Object byte[] 24
    $rng=[System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
}
function Write-ServerEnv([string]$databaseUrl,[string]$appPassword='',[bool]$portable=$false,[int]$port=5432) {
    $lines=@()
    if($appPassword) { $lines += "TRAINER_DB_PASSWORD=$appPassword" }
    $lines += "DATABASE_URL=$databaseUrl"
    $lines += 'ALLOW_SELF_REGISTRATION=0'
    if($portable) {
        $lines += 'PORTABLE_POSTGRES=1'
        $lines += "PORTABLE_POSTGRES_PORT=$port"
    }
    $lines += '# PUBLIC_ORIGIN=https://trainer.example.org'
    $lines | Set-Content -LiteralPath $envFile -Encoding UTF8
    $env:DATABASE_URL=$databaseUrl
    if($appPassword) { $env:TRAINER_DB_PASSWORD=$appPassword }
    if($portable) { $env:PORTABLE_POSTGRES='1'; $env:PORTABLE_POSTGRES_PORT="$port" }
}
function Load-EnvFile([string]$path) {
    if(-not (Test-Path -LiteralPath $path)) { return }
    foreach($line in Get-Content -LiteralPath $path -Encoding UTF8) {
        $v=$line.Trim(); if(-not $v -or $v.StartsWith('#') -or -not $v.Contains('=')) { continue }
        $p=$v.Split('=',2); [Environment]::SetEnvironmentVariable($p[0].Trim(),$p[1].Trim(),'Process')
    }
}
function Install-ServerDependencies {
    Write-Host '[112] Проверка Python-зависимостей PostgreSQL...' -ForegroundColor Cyan
    Invoke-Python -CommandArgs @('-m','pip','install','-r','requirements-server.txt','--disable-pip-version-check')
}
function Test-And-Migrate {
    Install-ServerDependencies
    Write-Host '[112] Проверяю соединение с PostgreSQL...' -ForegroundColor Cyan
    Invoke-Python -CommandArgs @('manage_db.py','status')
    Write-Host '[112] Применяю миграции...' -ForegroundColor Cyan
    Invoke-Python -CommandArgs @('manage_db.py','migrate')
}
function Ensure-Alias {
    $marker=Join-Path $runtime 'postgres-subst-drive.txt'
    if(Test-Path -LiteralPath $marker) {
        $saved=(Get-Content -LiteralPath $marker -Raw -ErrorAction SilentlyContinue).Trim().ToUpperInvariant()
        if($saved -match '^[A-Z]:$') {
            & subst.exe $saved /D 2>$null | Out-Null
            & subst.exe $saved $root | Out-Null
            if($LASTEXITCODE -eq 0) { return $saved }
        }
    }
    foreach($letter in @('N:','M:','L:','K:','J:','I:','H:','G:','F:')) {
        if(Test-Path ($letter + '\')) { continue }
        & subst.exe $letter $root | Out-Null
        if($LASTEXITCODE -eq 0) { Set-Content -LiteralPath $marker -Value $letter -NoNewline -Encoding ASCII; return $letter }
    }
    throw 'Не удалось создать короткий путь для portable PostgreSQL.'
}
function Get-FreePort {
    $used=@([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | ForEach-Object { $_.Port })
    foreach($candidate in 55432..55442) { if($used -notcontains $candidate) { return $candidate } }
    throw 'Не найден свободный локальный порт 55432-55442 для portable PostgreSQL.'
}
function Download-PortablePostgres {
    if(Test-Path -LiteralPath $portableZip) {
        $size=(Get-Item -LiteralPath $portableZip).Length
        if($size -gt 50000000) { return }
        Remove-Item -LiteralPath $portableZip -Force -ErrorAction SilentlyContinue
    }
    Write-Host '[112] PostgreSQL не установлен. Скачиваю portable PostgreSQL 16.15 (~100+ МБ)...' -ForegroundColor Cyan
    Write-Host '[112] Источник: EnterpriseDB (официальные Windows binaries).' -ForegroundColor DarkGray
    $download=Join-Path $runtime 'postgresql-download.tmp'
    Remove-Item -LiteralPath $download -Force -ErrorAction SilentlyContinue
    $curl=Get-Command curl.exe -ErrorAction SilentlyContinue
    if($curl) {
        # Schannel: ignore only unavailable revocation endpoints; keep certificate verification.
        & $curl.Source -L --fail --ssl-revoke-best-effort --retry 3 --retry-delay 2 -o $download $portableUrl
        if($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $download) -and (Get-Item -LiteralPath $download).Length -gt 50000000) {
            Move-Item -LiteralPath $download -Destination $portableZip -Force
            return
        }
        Remove-Item -LiteralPath $download -Force -ErrorAction SilentlyContinue
    }
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $portableUrl -OutFile $download
        if(-not (Test-Path -LiteralPath $download) -or (Get-Item -LiteralPath $download).Length -le 50000000) {
            throw 'Скачан неполный архив PostgreSQL.'
        }
        Move-Item -LiteralPath $download -Destination $portableZip -Force
    } catch {
        Remove-Item -LiteralPath $download -Force -ErrorAction SilentlyContinue
        throw "Не удалось скачать portable PostgreSQL. Поместите архив вручную в $portableZip. Подробности: $_"
    }
}
function Prepare-PortablePostgres {
    $drive=Ensure-Alias; $aliasRoot=$drive + '\'
    $pgHome=Join-Path $aliasRoot '.runtime\postgresql'
    $dataDir=Join-Path $aliasRoot '.runtime\postgres-data'
    $portFile=Join-Path $runtime 'postgres-port.txt'

    if(-not (Test-Path -LiteralPath (Join-Path $pgHome 'bin\initdb.exe'))) {
        Download-PortablePostgres
        $stage=Join-Path $aliasRoot '.runtime\postgresql-extract'
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $stage | Out-Null
        Write-Host '[112] Распаковываю portable PostgreSQL...' -ForegroundColor Cyan
        Expand-Archive -LiteralPath $portableZip -DestinationPath $stage -Force
        $init=Get-ChildItem -LiteralPath $stage -Filter initdb.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if(-not $init) { throw 'Архив PostgreSQL распакован, но initdb.exe не найден.' }
        $bin=Split-Path -Parent $init.FullName; $sourceRoot=Split-Path -Parent $bin
        Remove-Item -LiteralPath $pgHome -Recurse -Force -ErrorAction SilentlyContinue
        Move-Item -LiteralPath $sourceRoot -Destination $pgHome
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }

    $initdb=Join-Path $pgHome 'bin\initdb.exe'
    $pgCtl=Join-Path $pgHome 'bin\pg_ctl.exe'
    $psql=Join-Path $pgHome 'bin\psql.exe'
    $createdb=Join-Path $pgHome 'bin\createdb.exe'
    $pgReady=Join-Path $pgHome 'bin\pg_isready.exe'
    foreach($f in @($initdb,$pgCtl,$psql,$createdb,$pgReady)) { if(-not (Test-Path -LiteralPath $f)) { throw "Не найден $f" } }

    if((Test-Path -LiteralPath $dataDir) -and (Test-Path -LiteralPath (Join-Path $dataDir 'PG_VERSION')) -and (Test-Path -LiteralPath $envFile)) {
        Load-EnvFile $envFile
        if($env:PORTABLE_POSTGRES -eq '1' -and $env:DATABASE_URL) {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'START_PORTABLE_POSTGRES.ps1')
            if($LASTEXITCODE -ne 0) { throw 'Не удалось запустить существующий portable PostgreSQL.' }
            Test-And-Migrate
            Write-Host '[112] Существующая portable PostgreSQL уже настроена.' -ForegroundColor Green
            return
        }
    }

    # A previous setup can stop after initdb but before .env.server is written.
    # Never delete such a cluster: stop it and move it aside before a fresh setup.
    if(Test-Path -LiteralPath (Join-Path $dataDir 'PG_VERSION')) {
        & $pgCtl -D $dataDir status 1>$null 2>$null
        if($LASTEXITCODE -eq 0) {
            & $pgCtl -D $dataDir -m fast -w -t 30 stop
            if($LASTEXITCODE -ne 0) { throw 'Не удалось остановить незавершённый экземпляр PostgreSQL. Данные не тронуты.' }
        }
        $backup=Join-Path $aliasRoot ('.runtime\postgres-data-unconfigured-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,6))
        Move-Item -LiteralPath $dataDir -Destination $backup
        Write-Host "[112] Незавершённая база сохранена в $backup; настройку начинаю заново." -ForegroundColor Yellow
    } elseif(Test-Path -LiteralPath $dataDir) {
        Remove-Item -LiteralPath $dataDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    $port=Get-FreePort
    Set-Content -LiteralPath $portFile -Value $port -NoNewline -Encoding ASCII
    $postgresPassword=New-AppPassword
    $appPassword=New-AppPassword
    $pwFile=Join-Path $aliasRoot '.runtime\postgres-init-password.txt'
    Set-Content -LiteralPath $pwFile -Value $postgresPassword -NoNewline -Encoding ASCII
    try {
        Write-Host '[112] Инициализирую локальную базу данных...' -ForegroundColor Cyan
        & $initdb -D $dataDir -U postgres --encoding=UTF8 --locale=C --auth-host=scram-sha-256 --auth-local=trust "--pwfile=$pwFile"
        if($LASTEXITCODE -ne 0) { throw 'initdb завершился с ошибкой.' }
    } finally { Remove-Item -LiteralPath $pwFile -Force -ErrorAction SilentlyContinue }

    $conf=Join-Path $dataDir 'postgresql.conf'
    Add-Content -LiteralPath $conf -Encoding ASCII -Value @("listen_addresses = '127.0.0.1'","port = $port","max_connections = 50")
    $log=Join-Path $aliasRoot '.runtime\postgresql.log'
    Write-Host "[112] Запускаю portable PostgreSQL на порту $port..." -ForegroundColor Cyan
    & $pgCtl -D $dataDir -l $log -o "-p $port" -w -t 30 start
    if($LASTEXITCODE -ne 0) { throw "PostgreSQL не запустился. Лог: $log" }

    $old=$env:PGPASSWORD; $env:PGPASSWORD=$postgresPassword
    try {
        $roleSql=@"
DO `$`$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'trainer112') THEN
    CREATE ROLE trainer112 LOGIN PASSWORD '$appPassword';
  ELSE
    ALTER ROLE trainer112 WITH LOGIN PASSWORD '$appPassword';
  END IF;
END
`$`$;
"@
        # -c sends the ASCII SQL directly: Windows PowerShell 5 writes BOM with -Encoding UTF8.
        & $psql -h 127.0.0.1 -p $port -U postgres -d postgres -v ON_ERROR_STOP=1 -c $roleSql
        if($LASTEXITCODE -ne 0) { throw 'Не удалось создать роль trainer112.' }
        $exists=(& $psql -h 127.0.0.1 -p $port -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='trainer112';" 2>$null | Select-Object -First 1)
        if($exists) { $exists=$exists.ToString().Trim() }
        if($exists -ne '1') {
            & $createdb -h 127.0.0.1 -p $port -U postgres -O trainer112 -E UTF8 trainer112
            if($LASTEXITCODE -ne 0) { throw 'Не удалось создать базу trainer112.' }
        }
    } finally { $env:PGPASSWORD=$old }

    $databaseUrl="postgresql://trainer112:$appPassword@127.0.0.1`:$port/trainer112"
    Write-ServerEnv $databaseUrl $appPassword $true $port
    Test-And-Migrate
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor DarkGreen
    Write-Host ' Portable PostgreSQL настроен. Docker и установка PostgreSQL НЕ нужны.' -ForegroundColor Green
    Write-Host '============================================================' -ForegroundColor DarkGreen
    Write-Host "Порт БД: $port (только 127.0.0.1)" -ForegroundColor Cyan
    Write-Host 'Теперь создайте администратора (если его еще нет):' -ForegroundColor Green
    Write-Host '  py -3 manage_users.py create admin "Администратор" admin' -ForegroundColor Yellow
    Write-Host 'Затем запускайте START_SHARED_SERVER.cmd.' -ForegroundColor Green
}

function Find-Psql {
    $cmd=Get-Command psql.exe -ErrorAction SilentlyContinue; if($cmd){return $cmd.Source}
    $roots=@((Join-Path $env:ProgramFiles 'PostgreSQL'),(Join-Path ${env:ProgramFiles(x86)} 'PostgreSQL')) | Where-Object { $_ -and (Test-Path $_) }
    foreach($base in $roots) { foreach($v in (Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) { $c=Join-Path $v.FullName 'bin\psql.exe'; if(Test-Path $c){return $c} } }
    return $null
}
function Setup-InstalledPostgres {
    $psql=Find-Psql
    if(-not $psql){ throw 'PostgreSQL в Windows не найден. Выберите вариант 1, чтобы проект сам скачал portable PostgreSQL.' }
    $bin=Split-Path -Parent $psql; $createdb=Join-Path $bin 'createdb.exe'
    $dbHost=(Read-Host 'Хост PostgreSQL [127.0.0.1]').Trim(); if(-not $dbHost){$dbHost='127.0.0.1'}
    $dbPort=(Read-Host 'Порт PostgreSQL [5432]').Trim(); if(-not $dbPort){$dbPort='5432'}
    $superUser=(Read-Host 'Администратор PostgreSQL [postgres]').Trim(); if(-not $superUser){$superUser='postgres'}
    $secure=Read-Host "Пароль PostgreSQL пользователя $superUser" -AsSecureString
    $credential=New-Object System.Management.Automation.PSCredential($superUser,$secure); $superPassword=$credential.GetNetworkCredential().Password
    if(-not $superPassword){throw 'Пароль PostgreSQL не введен.'}
    $old=$env:PGPASSWORD; $env:PGPASSWORD=$superPassword
    try {
        $probe=& $psql -h $dbHost -p $dbPort -U $superUser -d postgres -v ON_ERROR_STOP=1 -tAc 'SELECT 1;' 2>&1
        if($LASTEXITCODE -ne 0 -or (($probe|Out-String).Trim() -notmatch '1')){throw 'Не удалось подключиться к установленному PostgreSQL.'}
        $appPassword=New-AppPassword
        $sql="DO `$`$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='trainer112') THEN CREATE ROLE trainer112 LOGIN PASSWORD '$appPassword'; ELSE ALTER ROLE trainer112 WITH LOGIN PASSWORD '$appPassword'; END IF; END `$`$;"
        & $psql -h $dbHost -p $dbPort -U $superUser -d postgres -v ON_ERROR_STOP=1 -c $sql | Out-Null
        $exists=(& $psql -h $dbHost -p $dbPort -U $superUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='trainer112';" 2>$null|Select-Object -First 1)
        if($exists){$exists=$exists.ToString().Trim()}
        if($exists -ne '1'){& $createdb -h $dbHost -p $dbPort -U $superUser -O trainer112 -E UTF8 trainer112; if($LASTEXITCODE -ne 0){throw 'Не удалось создать базу trainer112.'}}
    } finally { $env:PGPASSWORD=$old }
    $databaseUrl="postgresql://trainer112:$appPassword@$dbHost`:$dbPort/trainer112"; Write-ServerEnv $databaseUrl $appPassword $false ([int]$dbPort); Test-And-Migrate
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host ' Тренажер 112 - PostgreSQL БЕЗ Docker' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor DarkCyan
Write-Host '1 - Portable PostgreSQL: скачать и держать внутри проекта (рекомендуется)'
Write-Host '2 - Использовать PostgreSQL, уже установленный в Windows'
Write-Host '3 - Подключить внешний PostgreSQL по DATABASE_URL (VPS/облако)'
Write-Host ''
$mode=(Read-Host 'Выберите вариант [1]').Trim(); if(-not $mode){$mode='1'}
if($mode -eq '1'){Prepare-PortablePostgres; exit 0}
if($mode -eq '2'){Setup-InstalledPostgres; Write-Host 'Готово. Используется установленный PostgreSQL.' -ForegroundColor Green; exit 0}
if($mode -eq '3'){
    $databaseUrl=(Read-Host 'Вставьте DATABASE_URL (postgresql://...)').Trim(); if($databaseUrl -notmatch '^postgres(ql)?://'){throw 'Некорректный DATABASE_URL.'}
    Write-ServerEnv $databaseUrl; Test-And-Migrate; Write-Host 'Готово. Внешняя PostgreSQL подключена.' -ForegroundColor Green; exit 0
}
throw 'Неизвестный вариант. Выберите 1, 2 или 3.'
