$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime = Join-Path $root '.runtime'
$positions = @{}
$logs = @(
    @{ Name = 'WEB'; File = (Join-Path $runtime 'web-ui.out.log') },
    @{ Name = 'WEB ERROR'; File = (Join-Path $runtime 'web-ui.err.log') },
    @{ Name = 'AI'; File = (Join-Path $runtime 'ai-rest.out.log') },
    @{ Name = 'AI ERROR'; File = (Join-Path $runtime 'ai-rest.err.log') }
)

function Show-NewLogLines {
    foreach ($item in $logs) {
        $path = $item.File
        if (-not (Test-Path $path)) { continue }
        $stream = $null
        $reader = $null
        try {
            $stream = [System.IO.File]::Open($path, [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
            $position = if ($positions.ContainsKey($path)) { [long]$positions[$path] } else { 0L }
            if ($stream.Length -lt $position) { $position = 0L }
            [void]$stream.Seek($position, [System.IO.SeekOrigin]::Begin)
            $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
            while (-not $reader.EndOfStream) {
                $line = $reader.ReadLine()
                if ($line) { Write-Host "[$($item.Name)] $line" }
            }
            $positions[$path] = $stream.Position
        } catch {
            Write-Host "Could not read $($item.Name) log: $($_.Exception.Message)" -ForegroundColor Yellow
        } finally {
            if ($reader) { $reader.Dispose() } elseif ($stream) { $stream.Dispose() }
        }
    }
}

function Is-Running([string]$file) {
    if (-not (Test-Path $file)) { return $false }
    $value = (Get-Content $file -Raw -ErrorAction SilentlyContinue).Trim()
    if ($value -notmatch '^\d+$') { return $false }
    return [bool](Get-Process -Id ([int]$value) -ErrorAction SilentlyContinue)
}

Write-Host '112 server console - live status and REST requests' -ForegroundColor Cyan
Write-Host 'Browser: http://127.0.0.1:8878     Stop services: STOP.cmd' -ForegroundColor Gray
Write-Host 'Closing this console does not stop the servers.' -ForegroundColor Gray
Write-Host ''
$lastStatus = [DateTime]::MinValue
while ($true) {
    Show-NewLogLines
    if (((Get-Date) - $lastStatus).TotalSeconds -ge 10) {
        $web = Is-Running (Join-Path $runtime 'web-ui.pid')
        $aiFile = Join-Path $runtime 'ai-rest.pid'
        $aiStatus = if (Test-Path $aiFile) { if (Is-Running $aiFile) { 'running' } else { 'stopped' } } else { 'remote' }
        Write-Host ("[STATUS] web: {0} | AI: {1} | {2:HH:mm:ss}" -f $(if ($web) { 'running' } else { 'stopped' }), $aiStatus, (Get-Date)) -ForegroundColor $(if ($web) { 'Green' } else { 'Red' })
        $lastStatus = Get-Date
        if (-not $web) {
            Write-Host 'Web server stopped. Check errors above or run RESTART.cmd.' -ForegroundColor Yellow
            break
        }
    }
    Start-Sleep -Seconds 1
}
