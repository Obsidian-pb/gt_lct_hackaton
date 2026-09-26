param([switch]$Force)
$ErrorActionPreference = 'Stop'
$configPath = Join-Path $PSScriptRoot 'config.local.json'
if ((Test-Path -LiteralPath $configPath) -and -not $Force) { exit 0 }

. (Join-Path $PSScriptRoot 'setup_key.ps1')
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Подключение нейросети'
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(560, 320)
$form.MinimumSize = New-Object System.Drawing.Size(560, 320)
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.FormBorderStyle = 'FixedDialog'
$form.TopMost = $true

$title = New-Object System.Windows.Forms.Label
$title.Text = if ($Force) { 'Введите новый ключ GigaChat' } else { 'Первый запуск: нужен ключ GigaChat' }
$title.Font = New-Object System.Drawing.Font('Segoe UI', 14, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(24, 22)
$title.Size = New-Object System.Drawing.Size(500, 34)
$form.Controls.Add($title)

$info = New-Object System.Windows.Forms.Label
$info.Text = "Ключ в архив не встроен. Вставьте собственный ключ авторизации GigaChat. Он будет сохранён только в этой папке на вашем компьютере."
$info.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$info.Location = New-Object System.Drawing.Point(26, 63)
$info.Size = New-Object System.Drawing.Size(490, 48)
$form.Controls.Add($info)

$keyBox = New-Object System.Windows.Forms.TextBox
$keyBox.Location = New-Object System.Drawing.Point(28, 122)
$keyBox.Size = New-Object System.Drawing.Size(486, 28)
$keyBox.Font = New-Object System.Drawing.Font('Consolas', 10)
$keyBox.UseSystemPasswordChar = $true
$keyBox.TabIndex = 0
$form.Controls.Add($keyBox)

$show = New-Object System.Windows.Forms.CheckBox
$show.Text = 'Показать введённый ключ'
$show.Location = New-Object System.Drawing.Point(28, 158)
$show.Size = New-Object System.Drawing.Size(220, 24)
$show.Add_CheckedChanged({ $keyBox.UseSystemPasswordChar = -not $show.Checked })
$form.Controls.Add($show)

$note = New-Object System.Windows.Forms.Label
$note.Text = 'Можно вставить ключ с префиксом Basic — программа удалит его автоматически.'
$note.Font = New-Object System.Drawing.Font('Segoe UI', 8)
$note.ForeColor = [System.Drawing.Color]::DimGray
$note.Location = New-Object System.Drawing.Point(28, 188)
$note.Size = New-Object System.Drawing.Size(480, 30)
$form.Controls.Add($note)

$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = 'Отмена'
$cancel.Location = New-Object System.Drawing.Point(296, 228)
$cancel.Size = New-Object System.Drawing.Size(102, 34)
$cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.Controls.Add($cancel)

$save = New-Object System.Windows.Forms.Button
$save.Text = 'Сохранить и запустить'
$save.Location = New-Object System.Drawing.Point(404, 228)
$save.Size = New-Object System.Drawing.Size(112, 34)
$save.TabIndex = 1
$form.Controls.Add($save)
$form.AcceptButton = $save
$form.CancelButton = $cancel

$save.Add_Click({
    try {
        Save-GigaChatKey -Directory $PSScriptRoot -Key $keyBox.Text | Out-Null
        $form.Tag = 'saved'
        $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $form.Close()
    } catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Ключ не сохранён', 'OK', 'Error') | Out-Null
        $keyBox.SelectAll()
        $keyBox.Focus()
    }
})
$form.Add_Shown({ $keyBox.Focus() })
$result = $form.ShowDialog()
$form.Dispose()
if ($result -eq [System.Windows.Forms.DialogResult]::OK -and (Test-Path -LiteralPath $configPath)) { exit 0 }
exit 2
