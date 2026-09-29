$ErrorActionPreference='Stop'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime=Join-Path $root '.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

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
        if($LASTEXITCODE -eq 0) {
            Set-Content -LiteralPath $marker -Value $letter -NoNewline -Encoding ASCII
            return $letter
        }
    }
    throw 'Не удалось создать короткий путь для portable PostgreSQL (нет свободной буквы диска).'
}

$drive=Ensure-Alias
$aliasRoot=$drive + '\'
$pgHome=Join-Path $aliasRoot '.runtime\postgresql'
$dataDir=Join-Path $aliasRoot '.runtime\postgres-data'
$pgCtl=Join-Path $pgHome 'bin\pg_ctl.exe'
$pgReady=Join-Path $pgHome 'bin\pg_isready.exe'
$portFile=Join-Path $runtime 'postgres-port.txt'
if(-not (Test-Path -LiteralPath $pgCtl)) { throw 'Portable PostgreSQL не подготовлен. Сначала запустите SETUP_SHARED_SERVER.cmd.' }
if(-not (Test-Path -LiteralPath $dataDir)) { throw 'Каталог данных portable PostgreSQL не найден. Сначала запустите SETUP_SHARED_SERVER.cmd.' }
$port=55432
if(Test-Path -LiteralPath $portFile) {
    $raw=(Get-Content -LiteralPath $portFile -Raw -ErrorAction SilentlyContinue).Trim()
    if($raw -match '^\d+$') { $port=[int]$raw }
}

& $pgCtl -D $dataDir status 1>$null 2>$null
if($LASTEXITCODE -eq 0) {
    Write-Host "[112] Portable PostgreSQL уже работает на 127.0.0.1:$port" -ForegroundColor DarkGreen
    exit 0
}

$log=Join-Path $aliasRoot '.runtime\postgresql.log'
Write-Host "[112] Запуск portable PostgreSQL на 127.0.0.1:$port..." -ForegroundColor Cyan
& $pgCtl -D $dataDir -l $log -o "-p $port" -w -t 30 start
if($LASTEXITCODE -ne 0) { throw "Portable PostgreSQL не запустился. Лог: $log" }

for($i=0;$i -lt 30;$i++) {
    & $pgReady -h 127.0.0.1 -p $port 1>$null 2>$null
    if($LASTEXITCODE -eq 0) { Write-Host '[112] Portable PostgreSQL готов.' -ForegroundColor Green; exit 0 }
    Start-Sleep -Milliseconds 500
}
throw "Portable PostgreSQL запущен, но не отвечает на порту $port."
