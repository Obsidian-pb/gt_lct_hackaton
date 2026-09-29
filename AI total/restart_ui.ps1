$ErrorActionPreference = 'Stop'
$port = 8878
try {
    $moduleRoot = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 5
        if ($status.app -ne 'ai-project-ui' -or $status.root -ne $moduleRoot) {
            throw "На порту $port запущена другая программа или другая копия. Она не остановлена. Папка сервера: $($status.root)"
        }
        $processIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
        if ($processIds.Count -ne 1) { throw 'Нельзя однозначно определить процесс сервера.' }
        $serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($processIds[0])"
        if ($serverProcess.Name -notin @('python.exe', 'pythonw.exe') -or
            $serverProcess.CommandLine -notmatch '(^|[\s"/\\])web_ui\.py([\s"]|$)') {
            throw 'Процесс на порту не похож на сервер этого модуля. Он не остановлен.'
        }
        if ($status.pid -and $status.pid -ne $serverProcess.ProcessId) {
            throw 'Процесс сервера изменился. Повторите перезапуск.'
        }
        Write-Host "Останавливается сервер из папки: $moduleRoot"
        Stop-Process -Id $serverProcess.ProcessId -ErrorAction Stop
        Wait-Process -Id $serverProcess.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw 'Порт ещё занят. Повторите перезапуск через несколько секунд.'
        }
    }
    Write-Host 'Запускается обновлённый интерфейс…'
    & (Join-Path $moduleRoot 'START.cmd')
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось запустить Python. Проверьте установку Python 3.10 или новее.' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
