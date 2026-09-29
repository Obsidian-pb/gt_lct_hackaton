$ErrorActionPreference = 'Stop'
# Only GigaChat needs this additional root certificate. Other providers use the OS trust store.
$configPath = Join-Path $PSScriptRoot 'config.local.json'
if ($env:AI_PROJECT_CONFIG) { $configPath = $env:AI_PROJECT_CONFIG }
elseif ($env:AI_PROVIDER_CONFIG) { $configPath = $env:AI_PROVIDER_CONFIG }
elseif ($env:FIRE_SIM_GIGACHAT_CONFIG) { $configPath = $env:FIRE_SIM_GIGACHAT_CONFIG }
$provider = $env:AI_PROVIDER
try {
    $config = $null
    if (Test-Path -LiteralPath $configPath) { $config = [IO.File]::ReadAllText($configPath) | ConvertFrom-Json }
    if (-not $provider -or $provider -eq 'auto') { $provider = $config.provider }
    if (-not $provider -or $provider -eq 'auto') {
        $key = $env:AI_AUTHORIZATION_KEY
        if (-not $key) { $key = $env:GIGACHAT_CREDENTIALS }
        if (-not $key) { $key = $env:FIRE_SIM_GIGACHAT_AUTHORIZATION_KEY }
        if (-not $key) { $key = $config.authorization_key }
        if (-not $key) { $key = $config.credentials }
        if (-not $key -or $key -match '^(Basic\s+|Bearer\s+)?(sk-|AIza)') { exit 0 }
        if ($config.base_url -and $config.base_url -notmatch '^https://api\.giga\.chat/v1/?$') { exit 0 }
        $provider = 'gigachat'
    }
} catch { exit 0 }
if ($provider -ne 'gigachat') { exit 0 }
$certDir = Join-Path $PSScriptRoot 'certs'
$certPath = Join-Path $certDir 'ai_provider_root_ca.pem'
$url = 'https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt'

if (Test-Path -LiteralPath $certPath) { exit 0 }
New-Item -ItemType Directory -Force -Path $certDir | Out-Null
$tmp = Join-Path $certDir ('.ai-ca-' + [guid]::NewGuid().ToString('N') + '.tmp')
try {
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($null -eq $curl) {
        Write-Host 'Не найден curl.exe. Используется системное хранилище сертификатов Windows.' -ForegroundColor Yellow
        exit 0
    }
    & $curl.Source -L --fail --silent --show-error $url -o $tmp
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $tmp)) {
        throw 'Не удалось загрузить сертификат подключения.'
    }
    $text = [System.IO.File]::ReadAllText($tmp)
    if ($text -notmatch '-----BEGIN CERTIFICATE-----' -or $text -notmatch '-----END CERTIFICATE-----') {
        throw 'Получен файл неверного формата.'
    }
    Move-Item -LiteralPath $tmp -Destination $certPath -Force
    Write-Host 'Сертификат подключения ИИ подготовлен локально.' -ForegroundColor Green
    exit 0
} catch {
    Write-Host ('Не удалось автоматически подготовить сертификат ИИ: ' + $_.Exception.Message) -ForegroundColor Yellow
    Write-Host 'Программа продолжит запуск. Если ИИ не подключится, установите сертификат НУЦ Минцифры в Windows или повторите подготовку.' -ForegroundColor Yellow
    exit 0
} finally {
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
}
