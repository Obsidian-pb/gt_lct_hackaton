# Invoked by ВСТАВИТЬ_КЛЮЧ.cmd. Windows PowerShell 5.1 compatible.
$ErrorActionPreference = 'Stop'

function Save-GigaChatKey {
    param([string]$Directory, [string]$Key)

    $cleanKey = ($Key -replace '^\s*Basic\s+', '').Trim()
    if ([string]::IsNullOrWhiteSpace($cleanKey)) {
        throw 'Ключ не введён. Настройки не изменены.'
    }
    if ($cleanKey.Length -gt 16000 -or $cleanKey -match '\s' -or $cleanKey -match '[\x00-\x1f\x7f]') {
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
    $config | Add-Member -NotePropertyName authorization_key -NotePropertyValue $cleanKey -Force
    # Remove an older alias so a second credential is not retained in the file.
    $config.PSObject.Properties.Remove('credentials')
    foreach ($setting in @(
        @{Name='scope'; Value='GIGACHAT_API_PERS'},
        @{Name='model'; Value='pro'},
        @{Name='verify_ssl'; Value=$true}
    )) {
        if ($null -eq $config.PSObject.Properties[$setting.Name]) {
            $config | Add-Member -NotePropertyName $setting.Name -NotePropertyValue $setting.Value
        }
    }

    # Write beside the destination and atomically replace only a complete JSON file.
    $temporaryPath = Join-Path $Directory ('.gigachat-config-' + [guid]::NewGuid().ToString('N') + '.tmp')
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

# Dot-sourcing exposes the writer for tests without requesting a key or starting UI.
if ($MyInvocation.InvocationName -eq '.') { return }

$secret = $null
$pointer = [IntPtr]::Zero
$plainKey = $null
try {
    Write-Host ''
    Write-Host 'Настройка GigaChat' -ForegroundColor Cyan
    Write-Host 'Скопируйте свой ключ авторизации из кабинета GigaChat.'
    Write-Host 'Вставьте его правой кнопкой мыши или Ctrl+V и нажмите Enter.'
    Write-Host 'Символы ключа скрыты. Для отмены нажмите Ctrl+C.'
    Write-Host ''
    $secret = Read-Host 'Ключ авторизации' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $savedPath = Save-GigaChatKey -Directory $PSScriptRoot -Key $plainKey
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    $plainKey = $null
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($null -ne $secret) { $secret.Dispose() }
}

Write-Host ''
Write-Host 'Ключ сохранён в config.local.json рядом с программой.' -ForegroundColor Green
Write-Host 'Перезапускаю приложение с новым ключом…'
# Only this launch's environment is changed, never the user's persistent variables.
$env:AI_PROJECT_CONFIG = $savedPath
Remove-Item Env:GIGACHAT_CREDENTIALS -ErrorAction SilentlyContinue
Remove-Item Env:FIRE_SIM_GIGACHAT_AUTHORIZATION_KEY -ErrorAction SilentlyContinue
& (Join-Path $PSScriptRoot 'restart_ui.ps1')
exit $LASTEXITCODE
