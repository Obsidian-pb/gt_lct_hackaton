param([switch]$Force)
$ErrorActionPreference = 'Stop'
$configPath = Join-Path $PSScriptRoot 'config.local.json'
if ((Test-Path -LiteralPath $configPath) -and -not $Force) { exit 0 }
. (Join-Path $PSScriptRoot 'setup_key.ps1')
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$providers = @('openai', 'gigachat', 'gemini', 'anthropic', 'openai_compatible')
$labels = @('OpenAI (API для моделей GPT)', 'GigaChat', 'Google Gemini', 'Anthropic Claude', 'Другой OpenAI-совместимый API')
$urls = @('https://api.openai.com/v1', 'https://api.giga.chat/v1', 'https://generativelanguage.googleapis.com/v1beta/openai', 'https://api.anthropic.com/v1', '')
$existing = $null
if (Test-Path -LiteralPath $configPath) {
    try { $existing = [IO.File]::ReadAllText($configPath) | ConvertFrom-Json } catch { }
}
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Подключение ИИ'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = New-Object System.Drawing.Size(650, 548)
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Font
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.FormBorderStyle = 'FixedDialog'

function Add-Label([string]$Text, [int]$Y, [int]$Height = 24) {
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $Text
    $label.Location = New-Object System.Drawing.Point(24, $Y)
    $label.Size = New-Object System.Drawing.Size(602, $Height)
    $form.Controls.Add($label)
    return $label
}
$title = Add-Label 'Подключите свой ИИ-сервис' 18 34
$title.Font = New-Object System.Drawing.Font('Segoe UI', 15, [System.Drawing.FontStyle]::Bold)
$info = Add-Label 'Выберите сервис, который выдал ключ. Нужен API-ключ из кабинета разработчика, а не пароль или токен входа на сайт ChatGPT.' 58 48
$null = Add-Label 'Провайдер' 110
$providerBox = New-Object System.Windows.Forms.ComboBox
$providerBox.Location = New-Object System.Drawing.Point(24, 136)
$providerBox.Size = New-Object System.Drawing.Size(602, 28)
$providerBox.DropDownStyle = 'DropDownList'
$providerBox.Items.AddRange([object[]]$labels)
$providerBox.TabIndex = 0
$form.Controls.Add($providerBox)
$null = Add-Label 'API-ключ' 176
$keyBox = New-Object System.Windows.Forms.TextBox
$keyBox.Location = New-Object System.Drawing.Point(24, 202)
$keyBox.Size = New-Object System.Drawing.Size(602, 28)
$keyBox.UseSystemPasswordChar = $true
$keyBox.TabIndex = 1
$form.Controls.Add($keyBox)
$show = New-Object System.Windows.Forms.CheckBox
$show.Text = 'Показать введённый ключ'
$show.Location = New-Object System.Drawing.Point(24, 234)
$show.Size = New-Object System.Drawing.Size(300, 26)
$show.TabIndex = 2
$show.Add_CheckedChanged({ $keyBox.UseSystemPasswordChar = -not $show.Checked })
$form.Controls.Add($show)
$null = Add-Label 'Модель (auto — автоматический выбор; можно ввести точное имя)' 270
$modelBox = New-Object System.Windows.Forms.TextBox
$modelBox.Location = New-Object System.Drawing.Point(24, 298)
$modelBox.Size = New-Object System.Drawing.Size(602, 28)
$modelBox.TabIndex = 3
$form.Controls.Add($modelBox)
$null = Add-Label 'Базовый адрес API (без /chat/completions)' 336
$baseBox = New-Object System.Windows.Forms.TextBox
$baseBox.Location = New-Object System.Drawing.Point(24, 364)
$baseBox.Size = New-Object System.Drawing.Size(602, 28)
$baseBox.TabIndex = 4
$form.Controls.Add($baseBox)
$note = Add-Label 'Ключ хранится в config.local.json в этой папке. Не передавайте этот файл другим. Префиксы Basic и Bearer удаляются автоматически.' 404 58
$note.ForeColor = [System.Drawing.Color]::DimGray
$providerBox.Add_SelectedIndexChanged({
    $index = $providerBox.SelectedIndex
    $baseBox.Text = $urls[$index]
    $baseBox.ReadOnly = ($index -ne 4)
    $baseBox.TabStop = ($index -eq 4)
    $modelBox.Text = if ($index -eq 4) { '' } else { 'auto' }
})
$selected = 0
if ($null -ne $existing) {
    $found = [Array]::IndexOf($providers, [string]$existing.provider)
    if ($found -ge 0) { $selected = $found }
    elseif ($existing.base_url) {
        $foundUrl = [Array]::IndexOf($urls, ([string]$existing.base_url).TrimEnd('/'))
        $selected = if ($foundUrl -ge 0) { $foundUrl } else { 4 }
    }
    elseif ($existing.authorization_key -match '^(Basic\s+)?sk-ant-') { $selected = 3 }
    elseif ($existing.authorization_key -match '^(Bearer\s+)?AIza') { $selected = 2 }
    elseif ($existing.authorization_key -match '^(Bearer\s+)?sk-') { $selected = 0 }
    else { $selected = 1 }
}
$providerBox.SelectedIndex = $selected
if ($null -ne $existing) {
    if ($existing.model -and -not ($selected -ne 1 -and $existing.model -match '^GigaChat')) { $modelBox.Text = [string]$existing.model }
    if ($selected -eq 4 -and $existing.base_url) { $baseBox.Text = [string]$existing.base_url }
}
$existing = $null
$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = 'Отмена'
$cancel.Location = New-Object System.Drawing.Point(362, 488)
$cancel.Size = New-Object System.Drawing.Size(120, 36)
$cancel.TabIndex = 6
$cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.Controls.Add($cancel)
$save = New-Object System.Windows.Forms.Button
$save.Text = 'Сохранить'
$save.Location = New-Object System.Drawing.Point(498, 488)
$save.Size = New-Object System.Drawing.Size(128, 36)
$save.TabIndex = 5
$form.Controls.Add($save)
$form.AcceptButton = $save
$form.CancelButton = $cancel
$save.Add_Click({
    try {
        Save-AIKey -Directory $PSScriptRoot -Key $keyBox.Text -Provider $providers[$providerBox.SelectedIndex] -Model $modelBox.Text -BaseUrl $baseBox.Text | Out-Null
        $keyBox.Clear()
        $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $form.Close()
    } catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Настройки не сохранены', 'OK', 'Error') | Out-Null
        $keyBox.Focus()
    }
})
$form.Add_Shown({ $keyBox.Focus() })
$result = $form.ShowDialog()
$keyBox.Clear()
$form.Dispose()
if ($result -eq [System.Windows.Forms.DialogResult]::OK -and (Test-Path -LiteralPath $configPath)) { exit 0 }
exit 2
