$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$message = "Для запуска нужен Python 3.\n\nУстановить Python 3.12 для текущего пользователя автоматически?\nБудет загружен официальный установщик python.org."
$choice = [System.Windows.Forms.MessageBox]::Show($message, 'Python не найден', 'YesNo', 'Question')
if ($choice -ne [System.Windows.Forms.DialogResult]::Yes) { exit 2 }

$url = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$installer = Join-Path $env:TEMP ('python-ai-project-' + [guid]::NewGuid().ToString('N') + '.exe')
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $installer
    $signature = Get-AuthenticodeSignature -FilePath $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        throw 'Не удалось подтвердить цифровую подпись установщика Python.'
    }
    $proc = Start-Process -FilePath $installer -ArgumentList '/quiet','InstallAllUsers=0','PrependPath=1','Include_test=0','Include_launcher=1','SimpleInstall=1' -Wait -PassThru
    if ($proc.ExitCode -ne 0) { throw ('Установщик Python завершился с кодом ' + $proc.ExitCode + '.') }
    [System.Windows.Forms.MessageBox]::Show('Python установлен. Программа продолжит запуск.', 'Готово', 'OK', 'Information') | Out-Null
    exit 0
} catch {
    [System.Windows.Forms.MessageBox]::Show("Python не удалось установить автоматически.\n\n$($_.Exception.Message)\n\nУстановите Python 3 вручную с python.org и снова запустите START.cmd.", 'Ошибка установки', 'OK', 'Error') | Out-Null
    exit 1
} finally {
    if (Test-Path -LiteralPath $installer) { Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue }
}
