# Local AI authorization-key writer. Windows PowerShell 5.1 compatible.
$ErrorActionPreference = 'Stop'

function Save-AIKey {
    param([string]$Directory, [string]$Key,
          [ValidateSet('', 'openai', 'gigachat', 'gemini', 'anthropic', 'openai_compatible')]
          [string]$Provider = '', [string]$Model = 'auto', [string]$BaseUrl = '')

    $cleanKey = ($Key -replace '^\s*(Basic|Bearer)\s+', '').Trim()
    if ([string]::IsNullOrWhiteSpace($cleanKey)) {
        throw 'Ключ не введён. Настройки не изменены.'
    }
    if ($cleanKey.Length -gt 16000 -or $cleanKey -match '\s' -or $cleanKey -match '[^\x21-\x7e]') {
        throw 'В ключе есть пробелы или переносы строк. Скопируйте ключ авторизации целиком одной строкой.'
    }

    $configPath = Join-Path $Directory 'config.local.json'
    $config = [pscustomobject]@{}
    if (Test-Path -LiteralPath $configPath) {
        try {
            $config = [System.IO.File]::ReadAllText($configPath) | ConvertFrom-Json
            if ($null -eq $config -or $config -isnot [pscustomobject]) { throw 'Invalid configuration' }
        } catch {
            throw 'Не удалось прочитать config.local.json. Файл не изменён. Исправьте его формат перед повторным запуском.'
        }
    }
    if ($Provider) {
        $Model = $Model.Trim()
        if ([string]::IsNullOrWhiteSpace($Model)) { $Model = 'auto' }
        if ($Provider -eq 'openai_compatible') {
            $BaseUrl = $BaseUrl.Trim().TrimEnd('/')
            $parsed = $null
            if (-not [Uri]::TryCreate($BaseUrl, [UriKind]::Absolute, [ref]$parsed) -or
                $parsed.Scheme -ne 'https' -or -not $parsed.Host -or $parsed.UserInfo -or
                $parsed.Query -or $parsed.Fragment -or $BaseUrl -match '\s') {
                throw 'Укажите базовый HTTPS-адрес API без ключа, параметров и пароля.'
            }
            if ($Model -in @('auto', 'default', 'pro')) {
                throw 'Для совместимого API нужно точное имя текстовой модели.'
            }
        }
        if ($Provider -eq 'gigachat' -and $cleanKey -match '^(sk-|AIza)') {
            throw 'Ключ похож на ключ другого сервиса. Выберите своего провайдера вместо GigaChat.'
        }
        if ($Provider -eq 'openai' -and $cleanKey -match '^(sk-ant-|AIza)') {
            throw 'Ключ похож на ключ Claude или Gemini. Выберите соответствующего провайдера.'
        }
        if ($config.provider -ne $Provider) {
            foreach ($name in @('base_url', 'oauth_url', 'scope', 'ca_bundle')) {
                $config.PSObject.Properties.Remove($name)
            }
        }
        $config | Add-Member -NotePropertyName provider -NotePropertyValue $Provider -Force
        $config | Add-Member -NotePropertyName model -NotePropertyValue $Model -Force
        if ($Provider -eq 'openai_compatible') {
            $config | Add-Member -NotePropertyName base_url -NotePropertyValue $BaseUrl -Force
        } elseif ($Provider -ne 'gigachat') {
            $config.PSObject.Properties.Remove('base_url')
            $config.PSObject.Properties.Remove('oauth_url')
            $config.PSObject.Properties.Remove('scope')
        }
    }
    $config | Add-Member -NotePropertyName authorization_key -NotePropertyValue $cleanKey -Force
    $config.PSObject.Properties.Remove('credentials')
    foreach ($setting in @(
        @{Name='scope'; Value='auto'},
        @{Name='model'; Value='auto'},
        @{Name='verify_ssl'; Value=$true}
    )) {
        if ($null -eq $config.PSObject.Properties[$setting.Name]) {
            $config | Add-Member -NotePropertyName $setting.Name -NotePropertyValue $setting.Value
        }
    }

    $temporaryPath = Join-Path $Directory ('.ai-config-' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [System.IO.File]::WriteAllText($temporaryPath, ($config | ConvertTo-Json -Depth 32), (New-Object System.Text.UTF8Encoding($false)))
        if (Test-Path -LiteralPath $configPath) {
            [System.IO.File]::Replace($temporaryPath, $configPath, [NullString]::Value)
        } else {
            [System.IO.File]::Move($temporaryPath, $configPath)
        }
    } finally {
        if (Test-Path -LiteralPath $temporaryPath) { Remove-Item -LiteralPath $temporaryPath -Force }
    }
    return $configPath
}

# Backward-compatible internal function name used by older tests/scripts.
function Save-GigaChatKey {
    param([string]$Directory, [string]$Key)
    return Save-AIKey -Directory $Directory -Key $Key
}

if ($MyInvocation.InvocationName -eq '.') { return }

$secret = $null
$pointer = [IntPtr]::Zero
$plainKey = $null
try {
    Write-Host ''
    Write-Host 'Настройка ИИ' -ForegroundColor Cyan
    Write-Host 'Для выбора провайдера и модели используйте CHANGE_AI_KEY.cmd.'
    Write-Host 'Этот способ заменяет ключ с сохранением текущих настроек провайдера.'
    Write-Host 'Вставьте его правой кнопкой мыши или Ctrl+V и нажмите Enter.'
    Write-Host 'Символы ключа скрыты. Для отмены нажмите Ctrl+C.'
    Write-Host ''
    $secret = Read-Host 'Ключ авторизации' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $savedPath = Save-AIKey -Directory $PSScriptRoot -Key $plainKey
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    $plainKey = $null
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($null -ne $secret) { $secret.Dispose() }
}

Write-Host ''
Write-Host 'Ключ ИИ сохранён в config.local.json рядом с программой.' -ForegroundColor Green
Write-Host 'Перезапускаю приложение с новым ключом…'
$env:AI_PROJECT_CONFIG = $savedPath
Remove-Item Env:AI_AUTHORIZATION_KEY -ErrorAction SilentlyContinue
Remove-Item Env:GIGACHAT_CREDENTIALS -ErrorAction SilentlyContinue
Remove-Item Env:FIRE_SIM_GIGACHAT_AUTHORIZATION_KEY -ErrorAction SilentlyContinue
& (Join-Path $PSScriptRoot 'restart_ui.ps1')
exit $LASTEXITCODE
