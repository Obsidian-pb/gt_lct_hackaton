$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$runtime = Join-Path $root '.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$errorLog = Join-Path $runtime 'launcher-error.log'
Remove-Item $errorLog -Force -ErrorAction SilentlyContinue

function Step([string]$message) {
    Write-Host "[112] $message" -ForegroundColor Cyan
}

function Find-Python {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        # Resolve the actual interpreter through a temporary script. Avoid `-c` here:
        # Windows PowerShell 5.1/WindowsApps can strip quotes from Python code arguments.
        $probe = Join-Path $runtime ('.resolve-python-' + $PID + '.py')
        try {
            Set-Content -LiteralPath $probe -Value 'import sys; print(sys.executable)' -Encoding UTF8
            $resolved = (& $py.Source -3 $probe 2>$null | Select-Object -First 1)
            if ($resolved) {
                $resolved = $resolved.ToString().Trim()
                if (Test-Path $resolved) { return $resolved }
            }
        } finally {
            Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        }
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    return $null
}

function Stop-Listener([int]$port) {
    try {
        $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
        foreach ($item in $listeners) {
            if ($item.OwningProcess -and $item.OwningProcess -ne $PID) {
                Step "Stopping old process on port $port (PID $($item.OwningProcess))..."
                Stop-Process -Id $item.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        }
        if ($listeners.Count -gt 0) { Start-Sleep -Milliseconds 500 }
    } catch {
        # Get-NetTCPConnection may be unavailable on very old Windows. The bind check below will report the issue.
    }
}

function Stop-Old-Console {
    $path = Join-Path $runtime 'server-console.pid'
    if (-not (Test-Path $path)) { return }
    $oldPid = (Get-Content $path -Raw -ErrorAction SilentlyContinue).Trim()
    if ($oldPid -match '^\d+$' -and (Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue)) {
        & taskkill.exe /PID $oldPid /T /F 2>$null | Out-Null
    }
    Remove-Item $path -Force -ErrorAction SilentlyContinue
}

function Wait-Health([string]$url, [System.Diagnostics.Process]$process, [string]$stderrPath, [string]$expectedField = 'status', [string]$expectedValue = 'ok', [int]$attempts = 60) {
    for ($i = 0; $i -lt $attempts; $i++) {
        if ($process -and $process.HasExited) {
            $detail = ''
            if (Test-Path $stderrPath) { $detail = (Get-Content $stderrPath -Raw -ErrorAction SilentlyContinue).Trim() }
            if (-not $detail) { $detail = "Process exited with code $($process.ExitCode)." }
            throw $detail
        }
        try {
            $answer = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 2
            if ($answer.$expectedField -eq $expectedValue) { return $true }
        } catch {}
        Start-Sleep -Milliseconds 250
    }
    throw "Service did not become ready: $url"
}

try {
    Step 'Preparing one-click startup...'

    if (-not (Test-Path (Join-Path $root 'config.local.json'))) {
        Step 'First launch: configure your AITUNNEL key once.'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'FIRST_RUN_KEY.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'AI key setup was cancelled or failed.' }
    }

    Step 'Preparing secure AI connection...'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'PREPARE_AI_CONNECTION.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'PREPARE_AI_CONNECTION.ps1 failed.' }

    Step 'Building/updating the browser interface...'
    & (Join-Path $root 'BUILD_UI.cmd')
    if ($LASTEXITCODE -ne 0) { throw 'UI build failed.' }

    $python = Find-Python
    if (-not $python) {
        Step 'Python 3 not found; opening installer helper...'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'INSTALL_PYTHON.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Python installation was cancelled or failed.' }
        $python = Find-Python
        if (-not $python) { throw 'Python 3 was not found after installation.' }
    }
    Step "Python: $python"

    $dialogueUrl = if ($env:AI_DIALOGUE_REST_URL) { $env:AI_DIALOGUE_REST_URL.TrimEnd('/') } else { 'http://127.0.0.1:8890' }
    try { $dialogueUri = [Uri]$dialogueUrl } catch { throw 'AI_DIALOGUE_REST_URL must be a valid http(s)://host:port URL.' }
    if ($dialogueUri.Scheme -notin @('http','https')) { throw 'AI_DIALOGUE_REST_URL must use http or https.' }
    $localHosts = @('127.0.0.1','localhost','::1')
    $useLocalAi = $localHosts -contains $dialogueUri.Host

    # Stop the previous application BEFORE touching Piper packages. On Windows a running
    # Python process keeps native .pyd files (numpy/onnxruntime) locked and pip cannot
    # replace/delete them. This ordering prevents WinError 5 on repeated START.cmd.
    Step 'Stopping previous local services before Piper check...'
    Stop-Listener 8878
    if ($useLocalAi) { Stop-Listener $dialogueUri.Port }
    Stop-Old-Console
    Start-Sleep -Milliseconds 600

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'PREPARE_PIPER.ps1') -PythonPath $python
    if ($LASTEXITCODE -ne 0) { Step 'Piper setup could not finish. The interface will start, but local Piper voice is unavailable; see .runtime\piper-selftest.log.' }

    if (-not $env:AI_REST_TOKEN -or $env:AI_REST_TOKEN.Length -lt 24) {
        if ($useLocalAi) {
            # Per-launch internal bearer token. It is inherited by both local backend processes and never sent to the browser.
            $env:AI_REST_TOKEN = [Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N')
        } else {
            throw 'For a remote dedicated AI REST server, set AI_REST_TOKEN to the same value on both machines.'
        }
    }
    $env:AI_DIALOGUE_REST_URL = $dialogueUrl

    if ($useLocalAi) {
        $aiOut = Join-Path $runtime 'ai-rest.out.log'
        $aiErr = Join-Path $runtime 'ai-rest.err.log'
        Remove-Item $aiOut,$aiErr -Force -ErrorAction SilentlyContinue
        Step "Starting dedicated AI REST service locally at $dialogueUrl ..."
        $aiProcess = Start-Process -FilePath $python -ArgumentList @('ai_rest_server.py','--host','127.0.0.1','--port',"$($dialogueUri.Port)") -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $aiOut -RedirectStandardError $aiErr -PassThru
        Set-Content -Path (Join-Path $runtime 'ai-rest.pid') -Value $aiProcess.Id -NoNewline
        Wait-Health ($dialogueUrl + '/health') $aiProcess $aiErr 'status' 'ok' | Out-Null
        Step 'AI REST is ready.'
    } else {
        Step "Using remote AI REST service: $dialogueUrl"
        try {
            $remoteHealth = Invoke-RestMethod -Uri ($dialogueUrl + '/health') -Method Get -TimeoutSec 5
            if ($remoteHealth.status -ne 'ok') { throw 'Unexpected health response.' }
        } catch {
            throw "Remote AI REST is unavailable at $dialogueUrl. Start it on the dedicated machine and check firewall/port settings. $($_.Exception.Message)"
        }
        Step 'Remote AI REST is ready.'
    }

    $uiOut = Join-Path $runtime 'web-ui.out.log'
    $uiErr = Join-Path $runtime 'web-ui.err.log'
    Remove-Item $uiOut,$uiErr -Force -ErrorAction SilentlyContinue
<<<<<<< HEAD
    $uiHost = if ($env:TRAINING_LAN -eq '1') { '0.0.0.0' } else { '127.0.0.1' }
    Step "Starting main backend + frontend on $uiHost`:8878 ..."
    $uiProcess = Start-Process -FilePath $python -ArgumentList @('web_ui.py','--host',$uiHost,'--port','8878','--no-browser') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $uiOut -RedirectStandardError $uiErr -PassThru
=======
    Step 'Starting main backend + frontend on http://127.0.0.1:8878 ...'
    $uiProcess = Start-Process -FilePath $python -ArgumentList @('web_ui.py','--port','8878','--no-browser') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $uiOut -RedirectStandardError $uiErr -PassThru
>>>>>>> ec5491b6745f1dd11607901b6ecc81befa475fae
    Set-Content -Path (Join-Path $runtime 'web-ui.pid') -Value $uiProcess.Id -NoNewline
    Wait-Health 'http://127.0.0.1:8878/health' $uiProcess $uiErr 'app' 'ai-project-ui' | Out-Null

    Stop-Old-Console
    Step 'Opening a separate server console with live logs...'
    $console = Join-Path $root 'SERVER_CONSOLE.cmd'
    $consoleProcess = Start-Process -FilePath $env:ComSpec -WorkingDirectory $root -ArgumentList ('/k ""{0}""' -f $console) -PassThru
    Set-Content -Path (Join-Path $runtime 'server-console.pid') -Value $consoleProcess.Id -NoNewline

    Step 'Everything is ready. Opening the interface...'
<<<<<<< HEAD
    if ($env:TRAINING_LAN -eq '1') {
        $lanAddress = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne 'WellKnown' } | Select-Object -First 1 -ExpandProperty IPAddress
        if ($lanAddress) { Write-Host "Classroom address: http://$($lanAddress):8878/teacher" -ForegroundColor Green; Write-Host "Open that address yourself before copying the invite link. Learners must be on the same network." -ForegroundColor Yellow }
    }
    if ($env:TRAINING_LAN -eq '1' -and $lanAddress) { Start-Process ("http://$($lanAddress):8878/teacher") } else { Start-Process 'http://127.0.0.1:8878' }
=======
    Start-Process 'http://127.0.0.1:8878'
>>>>>>> ec5491b6745f1dd11607901b6ecc81befa475fae
    Write-Host ''
    Write-Host '112 is running. You can close this launcher window.' -ForegroundColor Green
    Write-Host 'To stop all local services, run STOP.cmd.' -ForegroundColor DarkGray
    Start-Sleep -Seconds 2
    exit 0
}
catch {
    $message = $_.Exception.Message
    $details = ($_ | Out-String)
    Set-Content -Path $errorLog -Value $details -Encoding UTF8
    Write-Host ''
    Write-Host "ERROR: $message" -ForegroundColor Red
    Write-Host "Details: $errorLog" -ForegroundColor Yellow
    exit 1
}
