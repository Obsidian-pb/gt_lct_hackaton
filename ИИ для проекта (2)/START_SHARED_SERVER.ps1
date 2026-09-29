$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$runtime = Join-Path $root '.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$startupLog = Join-Path $runtime 'shared-startup.log'
"[$(Get-Date -Format s)] START_SHARED_SERVER" | Set-Content -LiteralPath $startupLog -Encoding UTF8

function Step([string]$message) {
    Write-Host "[112] $message" -ForegroundColor Cyan
    Add-Content -LiteralPath $startupLog -Value "[$(Get-Date -Format s)] $message" -Encoding UTF8
}
function Load-EnvFile([string]$path) {
    if (-not (Test-Path $path)) { return }
    foreach ($line in Get-Content -LiteralPath $path -Encoding UTF8) {
        $value = $line.Trim()
        if (-not $value -or $value.StartsWith('#') -or -not $value.Contains('=')) { continue }
        $parts = $value.Split('=',2)
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), 'Process')
    }
}
function Find-PythonCommand {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) { return @{ Exe = $py.Source; Prefix = @('-3') } }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) { return @{ Exe = $python.Source; Prefix = @() } }
    throw 'Python 3 не найден.'
}
function Resolve-PythonExecutable {
    $cmd = Find-PythonCommand
    if ($cmd.Prefix.Count -eq 0) { return $cmd.Exe }
    $probe = Join-Path $runtime ('.resolve-shared-python-' + $PID + '.py')
    try {
        Set-Content -LiteralPath $probe -Value "import base64,sys; print(base64.b64encode(sys.executable.encode('utf-8')).decode('ascii'))" -Encoding UTF8
        $exe = $cmd.Exe; $prefix = @($cmd.Prefix)
        $lines = @(& $exe @prefix $probe 2>$null)
        if ($LASTEXITCODE -eq 0) {
            foreach ($line in $lines) {
                try {
                    $resolved = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($line.ToString().Trim()))
                    if (Test-Path -LiteralPath $resolved -PathType Leaf) { return $resolved }
                } catch [System.FormatException] { continue }
            }
        }
    } finally { Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue }
    throw 'Не удалось определить исполняемый файл Python через py -3.'
}
function Invoke-Python([string[]]$CommandArgs) {
    $cmd = Find-PythonCommand; $exe = $cmd.Exe; $prefix = @($cmd.Prefix)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $exe @prefix @CommandArgs
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw "Python command failed (exit $code): $($CommandArgs -join ' ')" }
}
function Start-Python([string[]]$CommandArgs, [string]$OutPath, [string]$ErrPath) {
    $cmd = Find-PythonCommand; $exe = $cmd.Exe; $all = @($cmd.Prefix) + @($CommandArgs)
    return Start-Process -FilePath $exe -ArgumentList $all -WorkingDirectory $root -RedirectStandardOutput $OutPath -RedirectStandardError $ErrPath -PassThru
}
function Stop-Listener([int]$port) {
    try {
        foreach ($item in @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) {
            if ($item.OwningProcess -and $item.OwningProcess -ne $PID) {
                Write-Host "[112] Останавливаю старый процесс на порту $port (PID $($item.OwningProcess))..." -ForegroundColor DarkGray
                Stop-Process -Id $item.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        }
        Start-Sleep -Milliseconds 400
    } catch {}
}
function Wait-Health([string]$url, [int]$attempts=80) {
    for ($i=0; $i -lt $attempts; $i++) {
        try {
            $r = Invoke-RestMethod -Uri $url -TimeoutSec 2
            if ($r.status -eq 'ok' -or $r.app -eq 'ai-project-ui' -or $r.data.status -eq 'ok') { return $r }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    throw "Сервис не запустился вовремя: $url"
}
function Tail-IfExists([string]$path) {
    if (Test-Path -LiteralPath $path) {
        Write-Host "----- $path -----" -ForegroundColor Yellow
        Get-Content -LiteralPath $path -Tail 30 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
    }
}

$ai = $null; $web = $null
$aiOut = Join-Path $runtime 'shared-ai-rest.out.log'; $aiErr = Join-Path $runtime 'shared-ai-rest.err.log'
$webOut = Join-Path $runtime 'shared-web.out.log'; $webErr = Join-Path $runtime 'shared-web.err.log'
try {
    Load-EnvFile (Join-Path $root '.env.server')
    if (-not $env:DATABASE_URL) { throw 'DATABASE_URL не задан. Сначала запустите SETUP_SHARED_SERVER.cmd.' }

    if ($env:PORTABLE_POSTGRES -eq '1') {
        Step 'Запускаю portable PostgreSQL...'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'START_PORTABLE_POSTGRES.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Portable PostgreSQL не запустился.' }
    }

    Stop-Listener 8878; Stop-Listener 8890
    $pythonExe = Resolve-PythonExecutable
    Step "Python: $pythonExe"

    Step 'Проверяю серверные Python-зависимости...'
    Invoke-Python -CommandArgs @('-m','pip','install','-r','requirements-server.txt','--disable-pip-version-check')

    Step 'Проверяю и применяю миграции PostgreSQL...'
    Invoke-Python -CommandArgs @('manage_db.py','migrate')

    # Do this early and visibly. On a fresh database getpass intentionally shows no characters while typing.
    Step 'Проверяю учётную запись администратора...'
    Write-Host '[112] Если база новая, сейчас будет предложено дважды ввести пароль первого администратора.' -ForegroundColor Yellow
    Write-Host '[112] При вводе пароля символы на экране НЕ отображаются — это нормально.' -ForegroundColor Yellow
    Invoke-Python -CommandArgs @('manage_users.py','bootstrap-admin')

    Step 'Подготавливаю защищённое AI-соединение...'
    if (-not (Test-Path (Join-Path $root 'config.local.json'))) {
        Write-Host '[112] Первый запуск: сохраните ключ AITUNNEL.' -ForegroundColor Yellow
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'FIRST_RUN_KEY.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Настройка AI-ключа отменена.' }
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'PREPARE_AI_CONNECTION.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось подготовить AI-соединение.' }

    Step 'Подготавливаю Piper (при ошибке сервер всё равно продолжит работу)...'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'PREPARE_PIPER.ps1') -PythonPath $pythonExe
    if ($LASTEXITCODE -ne 0) { Write-Host '[112] Piper недоступен; будет использован браузерный голос.' -ForegroundColor Yellow }

    Step 'Собираю интерфейс...'
    & (Join-Path $root 'BUILD_UI.cmd')
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось собрать интерфейс.' }

    if (-not $env:AI_REST_TOKEN -or $env:AI_REST_TOKEN.Length -lt 24) {
        $env:AI_REST_TOKEN = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
    }
    $env:AI_DIALOGUE_REST_URL = 'http://127.0.0.1:8890'
    Remove-Item $aiOut,$aiErr,$webOut,$webErr -Force -ErrorAction SilentlyContinue

    Step 'Запускаю AI REST на 127.0.0.1:8890...'
    $ai = Start-Python @('ai_rest_server.py','--host','127.0.0.1','--port','8890') $aiOut $aiErr
    Wait-Health 'http://127.0.0.1:8890/health' | Out-Null
    Set-Content -LiteralPath (Join-Path $runtime 'ai-rest.pid') -Value $ai.Id -NoNewline -Encoding ASCII

    $serverArgs = @('web_ui.py','--shared-server','--require-postgres','--auto-migrate','--host','0.0.0.0','--port','8878','--no-browser')
    if ($env:PUBLIC_ORIGIN) { $serverArgs += @('--public-origin',$env:PUBLIC_ORIGIN) }
    Step 'Запускаю общий сервер на 0.0.0.0:8878...'
    $web = Start-Python $serverArgs $webOut $webErr
    $health = Wait-Health 'http://127.0.0.1:8878/api/v1/health'
    Set-Content -LiteralPath (Join-Path $runtime 'web-ui.pid') -Value $web.Id -NoNewline -Encoding ASCII

    $backend = $health.data.storage.backend
    $schema = $health.data.storage.schema_version
    if ($backend -ne 'postgresql') { throw "Сервер запущен не через PostgreSQL (backend=$backend)." }

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor DarkGreen
    Write-Host ' СЕРВЕР 112 УСПЕШНО ЗАПУЩЕН' -ForegroundColor Green
    Write-Host '============================================================' -ForegroundColor DarkGreen
    Write-Host "PostgreSQL: $backend, schema v$schema" -ForegroundColor Green
    Write-Host 'Локально: http://127.0.0.1:8878/' -ForegroundColor Cyan
    Write-Host 'Для других ПК: http://IP_ЭТОГО_КОМПЬЮТЕРА:8878/' -ForegroundColor Cyan
    Write-Host 'Остановить всё: STOP.cmd' -ForegroundColor DarkGray
    Add-Content -LiteralPath $startupLog -Value "[$(Get-Date -Format s)] READY backend=$backend schema=$schema web_pid=$($web.Id) ai_pid=$($ai.Id)" -Encoding UTF8
    Start-Process 'http://127.0.0.1:8878/' | Out-Null
    exit 0
}
catch {
    $message = $_.Exception.Message
    Add-Content -LiteralPath $startupLog -Value "[$(Get-Date -Format s)] ERROR $message" -Encoding UTF8
    Write-Host ''
    Write-Host "[112] ОШИБКА ЗАПУСКА: $message" -ForegroundColor Red
    Tail-IfExists $webErr
    Tail-IfExists $aiErr
    Write-Host "[112] Полный журнал: $startupLog" -ForegroundColor Yellow
    if ($web -and -not $web.HasExited) { Stop-Process -Id $web.Id -Force -ErrorAction SilentlyContinue }
    if ($ai -and -not $ai.HasExited) { Stop-Process -Id $ai.Id -Force -ErrorAction SilentlyContinue }
    exit 1
}
