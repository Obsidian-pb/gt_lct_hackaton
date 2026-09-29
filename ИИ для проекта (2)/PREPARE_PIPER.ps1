param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtime = Join-Path $root '.runtime'
$voiceDir = Join-Path $root 'piper_voices'
$legacyPackages = Join-Path $runtime 'piper_packages'
$markerPath = Join-Path $runtime 'piper-packages-path.txt'
$logDir = $runtime
$selfTestLog = Join-Path $logDir 'piper-selftest.log'
$readyMarker = Join-Path $runtime 'piper-ready.json'
$espeakMarker = Join-Path $runtime 'piper-espeak-data-path.txt'
$substMarker = Join-Path $runtime 'piper-subst-drive.txt'
New-Item -ItemType Directory -Force -Path $voiceDir,$runtime,$logDir | Out-Null
Remove-Item -LiteralPath $readyMarker -Force -ErrorAction SilentlyContinue

function Say([string]$text,[ConsoleColor]$color=[ConsoleColor]::Cyan) {
    Write-Host "[Piper] $text" -ForegroundColor $color
}

if (-not $PythonPath) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        # Do not use `python -c` here. Windows PowerShell 5.1 combined with some
        # WindowsApps/Python launchers can strip quotes from the code argument.
        $resolveScript = Join-Path $runtime ('.resolve-python-' + $PID + '.py')
        try {
            Set-Content -LiteralPath $resolveScript -Value 'import sys; print(sys.executable)' -Encoding UTF8
            $resolved = (& $launcher.Source -3 $resolveScript 2>$null | Select-Object -First 1)
            if ($resolved) { $PythonPath = $resolved.ToString().Trim() }
        } finally {
            Remove-Item -LiteralPath $resolveScript -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not $PythonPath) {
        $python = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($python) { $PythonPath = $python.Source }
    }
}
if (-not $PythonPath -or -not (Test-Path $PythonPath)) {
    Say 'Python not found. Start the application with START.cmd.' Yellow
    exit 1
}

$names = @('ru_RU-irina-medium','ru_RU-denis-medium','ru_RU-dmitri-medium')
$downloads = if ($env:USERPROFILE) { Join-Path $env:USERPROFILE 'Downloads' } else { '' }

# First import any models the user has already placed next to START.cmd or in Downloads.
foreach ($name in $names) {
    foreach ($suffix in @('.onnx','.onnx.json')) {
        $destination = Join-Path $voiceDir ($name + $suffix)
        if (Test-Path -LiteralPath $destination) { continue }
        foreach ($folder in @($root,$downloads)) {
            if (-not $folder) { continue }
            $source = Join-Path $folder ($name + $suffix)
            if (Test-Path -LiteralPath $source) {
                Copy-Item -LiteralPath $source -Destination $destination -Force
                Say "Imported $name$suffix" Green
                break
            }
        }
    }
}

$separator = [System.IO.Path]::PathSeparator
$basePythonPath = $env:PYTHONPATH

function Set-PiperPythonPath([string]$packageDir) {
    if ($basePythonPath) {
        $env:PYTHONPATH = $packageDir + $separator + $root + $separator + $basePythonPath
    } else {
        $env:PYTHONPATH = $packageDir + $separator + $root
    }
}

function Invoke-PythonSnippet([string]$name, [string]$code) {
    # Execute Python from a temporary UTF-8 file instead of `python -c`.
    # This is intentionally more verbose but is reliable on Windows PowerShell 5.1,
    # paths with Cyrillic characters, and the WindowsApps python.exe launcher.
    $scriptPath = Join-Path $runtime ('.' + $name + '-' + $PID + '.py')
    try {
        Set-Content -LiteralPath $scriptPath -Value $code -Encoding UTF8
        $previous = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $output = @(& $PythonPath $scriptPath 2>&1)
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previous
        }
        return [PSCustomObject]@{
            ExitCode = $exitCode
            Output = $output
        }
    } catch {
        return [PSCustomObject]@{
            ExitCode = 1
            Output = @($_ | Out-String)
        }
    } finally {
        Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue
    }
}

function Test-PiperImportAt([string]$packageDir) {
    if (-not $packageDir -or -not (Test-Path -LiteralPath $packageDir)) { return $false }
    $saved = $env:PYTHONPATH
    try {
        if ($basePythonPath) {
            $env:PYTHONPATH = $packageDir + $separator + $root + $separator + $basePythonPath
        } else {
            $env:PYTHONPATH = $packageDir + $separator + $root
        }
        $probe = Invoke-PythonSnippet 'piper-import-probe' @'
from piper import PiperVoice
import numpy
import onnxruntime
print("ok")
'@
        return $probe.ExitCode -eq 0
    } finally {
        $env:PYTHONPATH = $saved
    }
}

function Resolve-MarkerPackage {
    if (-not (Test-Path -LiteralPath $markerPath)) { return $null }
    $raw = (Get-Content -LiteralPath $markerPath -Raw -ErrorAction SilentlyContinue).Trim()
    if (-not $raw) { return $null }
    if ([System.IO.Path]::IsPathRooted($raw)) { return $raw }
    return (Join-Path $runtime $raw)
}

function Save-ActivePackage([string]$packageDir) {
    # Store only the directory name so the project can be moved to another folder/PC.
    $leaf = Split-Path -Leaf $packageDir
    Set-Content -LiteralPath $markerPath -Value $leaf -NoNewline -Encoding ASCII
}

# Determine the interpreter tag without Python source-code quoting on the command line.
$versionOutput = @(& $PythonPath --version 2>&1)
$versionLine = if ($versionOutput.Count -gt 0) { $versionOutput[0].ToString().Trim() } else { '' }
if ($versionLine -match '^Python\s+(\d+)\.(\d+)') {
    $pythonTag = 'py' + $Matches[1] + $Matches[2]
} else {
    $pythonTag = 'py3'
    Say "Could not parse Python version from '$versionLine'; using runtime tag $pythonTag." Yellow
}
$preferredPackages = Join-Path $runtime ("piper_packages_${pythonTag}_v1_8_0")

# Reuse an already working runtime. Most importantly, do NOT call pip --upgrade on every launch.
$candidates = @()
$marked = Resolve-MarkerPackage
if ($marked) { $candidates += $marked }
$candidates += $preferredPackages
$candidates += $legacyPackages
$activePackages = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (Test-PiperImportAt $candidate) {
        $activePackages = $candidate
        break
    }
}

if (-not $activePackages) {
    Say 'Installing local Piper runtime (first launch/repair only)...'
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddHHmmss')
    $stage = Join-Path $runtime (".piper-install-$PID-$stamp")
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $PythonPath -m pip install --disable-pip-version-check --only-binary=:all: --target $stage 'piper-tts==1.8.0'
        $installCode = $LASTEXITCODE
    } catch {
        $installCode = 1
    } finally {
        $ErrorActionPreference = $previous
    }

    if ($installCode -ne 0 -or -not (Test-PiperImportAt $stage)) {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
        Say 'Piper runtime installation failed. Internet is required on the first launch.' Yellow
        exit 2
    }

    # Never overwrite/delete a package directory that another Python process may still have loaded.
    # Publish the completed staging directory under a fresh versioned name and switch via marker.
    $target = $preferredPackages
    if (Test-Path -LiteralPath $target) {
        $target = Join-Path $runtime ("piper_packages_${pythonTag}_v1_8_0_repair_$stamp")
    }
    try {
        Move-Item -LiteralPath $stage -Destination $target -Force
    } catch {
        # A move can be blocked by antivirus/indexing. Keep the fully installed staging folder as active.
        $target = $stage
    }
    $activePackages = $target
    Say "Piper runtime ready: $(Split-Path -Leaf $activePackages)" Green
}

Save-ActivePackage $activePackages
Set-PiperPythonPath $activePackages

# eSpeak NG on Windows is sensitive to non-ASCII/deep data paths. The project may live
# under a Cyrillic directory (for example E:\ХАКАТОН\...), so expose the project through
# a temporary drive-letter alias and pass the resulting short ASCII path explicitly.
function Remove-PreviousPiperSubst {
    if (-not (Test-Path -LiteralPath $substMarker)) { return }
    $oldDrive = (Get-Content -LiteralPath $substMarker -Raw -ErrorAction SilentlyContinue).Trim()
    if ($oldDrive -match '^[A-Z]:$') {
        & subst.exe $oldDrive /D 2>$null | Out-Null
    }
    Remove-Item -LiteralPath $substMarker -Force -ErrorAction SilentlyContinue
}

function New-PiperAsciiAlias([string]$packageDir) {
    Remove-PreviousPiperSubst
    $leaf = Split-Path -Leaf $packageDir
    $existingDrives = @([System.IO.DriveInfo]::GetDrives() | ForEach-Object { $_.Name.Substring(0,2).ToUpperInvariant() })
    $substText = @(& subst.exe 2>$null)
    foreach ($letter in @('T','U','V','W','X','Y','Z','S','R','Q','P')) {
        $drive = $letter + ':'
        if ($existingDrives -contains $drive) { continue }
        if ($substText | Where-Object { $_ -match ('^' + [regex]::Escape($drive)) }) { continue }
        $previous = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & subst.exe $drive $root | Out-Null
            $code = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previous
        }
        if ($code -ne 0) { continue }
        $aliasData = $drive + '\.runtime\' + $leaf + '\piper\espeak-ng-data'
        if (Test-Path -LiteralPath (Join-Path $aliasData 'phontab')) {
            Set-Content -LiteralPath $substMarker -Value $drive -NoNewline -Encoding ASCII
            Set-Content -LiteralPath $espeakMarker -Value $aliasData -NoNewline -Encoding ASCII
            return $aliasData
        }
        & subst.exe $drive /D 2>$null | Out-Null
    }
    return $null
}

$packageEspeak = Join-Path $activePackages 'piper\espeak-ng-data'
if (-not (Test-Path -LiteralPath (Join-Path $packageEspeak 'phontab'))) {
    Say 'Piper package does not contain espeak-ng-data\phontab.' Red
    exit 5
}
$espeakAlias = New-PiperAsciiAlias $activePackages
if (-not $espeakAlias) {
    Say 'Could not create a short ASCII path for eSpeak data. Check subst.exe availability.' Red
    exit 6
}
$env:PIPER_ESPEAK_DATA_DIR = $espeakAlias
Say "eSpeak data alias: $espeakAlias" Green

# If voice models are absent, download the three supported Russian voices automatically.
# piper.download_voices uses the official Piper voice catalogue.
foreach ($name in $names) {
    $model = Join-Path $voiceDir ($name + '.onnx')
    $config = Join-Path $voiceDir ($name + '.onnx.json')
    $validModel = (Test-Path -LiteralPath $model) -and ((Get-Item -LiteralPath $model).Length -gt 1000000)
    $validConfig = (Test-Path -LiteralPath $config) -and ((Get-Item -LiteralPath $config).Length -gt 100)
    if ($validModel -and $validConfig) { continue }

    Say "Downloading voice $name (first launch only, about 63 MB)..."
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $PythonPath -m piper.download_voices --data-dir $voiceDir $name
        $downloadCode = $LASTEXITCODE
    } catch { $downloadCode = 1 } finally { $ErrorActionPreference = $previous }

    $validModel = (Test-Path -LiteralPath $model) -and ((Get-Item -LiteralPath $model).Length -gt 1000000)
    $validConfig = (Test-Path -LiteralPath $config) -and ((Get-Item -LiteralPath $config).Length -gt 100)
    if ($downloadCode -ne 0 -or -not $validModel -or -not $validConfig) {
        Say "Could not download $name. You can still use another downloaded voice." Yellow
        Remove-Item -LiteralPath $model -Force -ErrorAction SilentlyContinue
    } else {
        Say "Voice ready: $name" Green
    }
}

$ready = @($names | Where-Object {
    $model = Join-Path $voiceDir ($_ + '.onnx')
    $config = Join-Path $voiceDir ($_ + '.onnx.json')
    (Test-Path -LiteralPath $model) -and ((Get-Item -LiteralPath $model).Length -gt 1000000) -and
    (Test-Path -LiteralPath $config) -and ((Get-Item -LiteralPath $config).Length -gt 100)
})
if (-not $ready.Count) {
    Say 'No usable Piper voice could be prepared. Check internet access and .runtime\piper-selftest.log.' Red
    exit 3
}

# Real synthesis smoke test. This catches a present-but-broken ONNX/runtime before the browser opens.
$testVoice = if ($ready -contains 'ru_RU-irina-medium') { 'ru_RU-irina-medium' } else { $ready[0] }
$testCode = @"
import base64
import piper_tts
r = piper_tts.synthesize('Проверка голоса очевидца.', '$testVoice')
raw = base64.b64decode(r['audio'].split(',', 1)[1])
assert raw[:4] == b'RIFF' and len(raw) > 1000, 'invalid wav'
print(r['voice'], len(raw))
"@
$env:PIPER_SELFTEST_BOOTSTRAP = '1'
try {
    $selfTest = Invoke-PythonSnippet 'piper-selftest' $testCode
} finally {
    Remove-Item Env:PIPER_SELFTEST_BOOTSTRAP -ErrorAction SilentlyContinue
}
$selfTestCode = $selfTest.ExitCode
$selfTest.Output | Set-Content -Path $selfTestLog -Encoding UTF8
if ($selfTestCode -ne 0) {
    Remove-Item -LiteralPath $readyMarker -Force -ErrorAction SilentlyContinue
    Say 'Voice files exist, but real WAV synthesis failed. See .runtime\piper-selftest.log.' Red
    exit 4
}

$readyPayload = [ordered]@{
    ready = $true
    runtime = (Split-Path -Leaf $activePackages)
    espeak_data_dir = $espeakAlias
    voices = $ready
    tested_at = [DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json -Depth 4
Set-Content -LiteralPath $readyMarker -Value $readyPayload -Encoding UTF8
Say ("Ready and tested: " + ($ready -join ', ')) Green
exit 0
