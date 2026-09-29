$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime = Join-Path $root '.runtime'
$stopped = @()
foreach ($name in @('web-ui.pid','ai-rest.pid')) {
    $path = Join-Path $runtime $name
    if (Test-Path $path) {
        $idText = (Get-Content $path -Raw).Trim()
        if ($idText -match '^\d+$') {
            $proc = Get-Process -Id ([int]$idText) -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-Process -Id $proc.Id -Force
                $stopped += $proc.Id
            }
        }
        Remove-Item $path -Force
    }
}
foreach ($port in @(8878,8890)) {
    foreach ($item in @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) {
        if ($item.OwningProcess -and ($stopped -notcontains $item.OwningProcess)) {
            Stop-Process -Id $item.OwningProcess -Force -ErrorAction SilentlyContinue
            $stopped += $item.OwningProcess
        }
    }
}
$consolePidPath = Join-Path $runtime 'server-console.pid'
if (Test-Path $consolePidPath) {
    $consoleId = (Get-Content $consolePidPath -Raw).Trim()
    if ($consoleId -match '^\d+$' -and (Get-Process -Id ([int]$consoleId) -ErrorAction SilentlyContinue)) {
        & taskkill.exe /PID $consoleId /T /F 2>$null | Out-Null
    }
    Remove-Item $consolePidPath -Force
}
$substMarker = Join-Path $runtime 'piper-subst-drive.txt'
if (Test-Path -LiteralPath $substMarker) {
    $drive = (Get-Content -LiteralPath $substMarker -Raw -ErrorAction SilentlyContinue).Trim()
    if ($drive -match '^[A-Z]:$') { & subst.exe $drive /D 2>$null | Out-Null }
    Remove-Item -LiteralPath $substMarker -Force -ErrorAction SilentlyContinue
}
$portableStop = Join-Path $root 'STOP_PORTABLE_POSTGRES.ps1'
if (Test-Path -LiteralPath $portableStop) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $portableStop 1>$null 2>$null
}
Write-Host '112 services stopped.' -ForegroundColor Green
exit 0
