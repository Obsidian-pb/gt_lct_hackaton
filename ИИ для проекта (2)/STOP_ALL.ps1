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
Write-Host '112 services stopped.' -ForegroundColor Green
exit 0
