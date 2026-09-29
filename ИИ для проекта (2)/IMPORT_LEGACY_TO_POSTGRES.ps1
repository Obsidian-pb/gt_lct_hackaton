$ErrorActionPreference='Stop'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$envFile=Join-Path $root '.env.server'
if (-not (Test-Path $envFile)) { throw '.env.server не найден. Сначала настройте общий сервер.' }
foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
    $v=$line.Trim(); if (-not $v -or $v.StartsWith('#') -or -not $v.Contains('=')) { continue }
    $parts=$v.Split('=',2); [Environment]::SetEnvironmentVariable($parts[0].Trim(),$parts[1].Trim(),'Process')
}
$py=Get-Command py.exe -ErrorAction SilentlyContinue
if ($py) { & $py.Source -3 manage_db.py import-legacy --data-dir data }
else { & python.exe manage_db.py import-legacy --data-dir data }
if ($LASTEXITCODE -ne 0) { throw 'Импорт завершился ошибкой.' }
