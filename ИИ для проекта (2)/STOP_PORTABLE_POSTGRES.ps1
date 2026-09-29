$ErrorActionPreference='SilentlyContinue'
$root=Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime=Join-Path $root '.runtime'
$marker=Join-Path $runtime 'postgres-subst-drive.txt'
$drive=$null
if(Test-Path -LiteralPath $marker) { $drive=(Get-Content -LiteralPath $marker -Raw -ErrorAction SilentlyContinue).Trim().ToUpperInvariant() }
if($drive -and $drive -match '^[A-Z]:$') {
    & subst.exe $drive /D 2>$null | Out-Null
    & subst.exe $drive $root | Out-Null
    $pgHome=Join-Path ($drive + '\') '.runtime\postgresql'
    $dataDir=Join-Path ($drive + '\') '.runtime\postgres-data'
    $pgCtl=Join-Path $pgHome 'bin\pg_ctl.exe'
    if((Test-Path -LiteralPath $pgCtl) -and (Test-Path -LiteralPath $dataDir)) {
        & $pgCtl -D $dataDir status 1>$null 2>$null
        if($LASTEXITCODE -eq 0) {
            Write-Host '[112] Остановка portable PostgreSQL...' -ForegroundColor DarkGray
            & $pgCtl -D $dataDir -m fast -w -t 20 stop 1>$null 2>$null
        }
    }
    & subst.exe $drive /D 2>$null | Out-Null
}
Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue
exit 0
