$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$runtime = Join-Path $root '.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function Step([string]$message) { Write-Host "[RESET ADMIN] $message" -ForegroundColor Cyan }
function Same-ProjectRunning {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8878/health' -Method Get -TimeoutSec 2
        if ($health.app -ne 'ai-project-ui' -or -not $health.root) { return $false }
        $running = [IO.Path]::GetFullPath([string]$health.root).TrimEnd('\')
        $expected = [IO.Path]::GetFullPath($root).TrimEnd('\')
        return [string]::Equals($running, $expected, [StringComparison]::OrdinalIgnoreCase)
    } catch { return $false }
}

try {
    Write-Host ''
    Write-Host 'СБРОС УЧЁТНОЙ ЗАПИСИ АДМИНИСТРАТОРА' -ForegroundColor Yellow
    Write-Host 'Карточки, тренировки, результаты, пользователи и учебные роли НЕ удаляются.'
    Write-Host 'Будут сброшены только логин/пароль администратора в текущем браузере.'
    Write-Host ''
    $answer = Read-Host 'Продолжить? Введите ДА'
    if ($answer.Trim().ToUpperInvariant() -notin @('ДА','YES','Y')) {
        Write-Host 'Сброс отменён.'
        exit 0
    }

    if (-not (Same-ProjectRunning)) {
        Step 'Проект не запущен. Запускаю текущую сборку...'
        & $env:ComSpec /c ('"{0}"' -f (Join-Path $root 'START.cmd'))
        if ($LASTEXITCODE -ne 0) { throw 'START.cmd завершился с ошибкой.' }
        for ($i=0; $i -lt 40 -and -not (Same-ProjectRunning); $i++) { Start-Sleep -Milliseconds 500 }
        if (-not (Same-ProjectRunning)) { throw 'Не удалось запустить локальный интерфейс на 127.0.0.1:8878.' }
    }

    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
    $tokenFile = Join-Path $runtime 'admin-reset-token.txt'
    [IO.File]::WriteAllText($tokenFile, $token, [Text.Encoding]::ASCII)

    Step 'Открываю одноразовую страницу сброса...'
    $url = 'http://127.0.0.1:8878/admin-reset?token=' + [Uri]::EscapeDataString($token)
    Start-Process $url
    Write-Host ''
    Write-Host 'В браузере нажмите «Сбросить администратора».' -ForegroundColor Green
    Write-Host 'Ссылка действует 10 минут и используется один раз.' -ForegroundColor DarkGray
    Start-Sleep -Seconds 2
    exit 0
}
catch {
    Write-Host ''
    Write-Host ('ОШИБКА: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Если проект уже открыт, закройте его через STOP.cmd и повторите.' -ForegroundColor Yellow
    exit 1
}
