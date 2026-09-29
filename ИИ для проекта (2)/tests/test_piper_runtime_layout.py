from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prepare_piper_does_not_upgrade_in_place():
    text = (ROOT / 'PREPARE_PIPER.ps1').read_text(encoding='utf-8-sig')
    assert '--upgrade --target' not in text
    assert '.piper-install-' in text
    assert 'piper-packages-path.txt' in text


def test_start_stops_old_services_before_preparing_piper():
    text = (ROOT / 'START_ALL.ps1').read_text(encoding='utf-8-sig')
    stop = text.index("Stop-Listener 8878")
    prepare = text.index("'PREPARE_PIPER.ps1'")
    assert stop < prepare


def test_prepare_piper_avoids_python_dash_c_quoting():
    text = (ROOT / 'PREPARE_PIPER.ps1').read_text(encoding='utf-8-sig')
    assert "$PythonPath -c" not in text
    assert "Invoke-PythonSnippet" in text
    assert "$PythonPath --version" in text


def test_start_python_resolution_avoids_dash_c_quoting():
    text = (ROOT / 'START_ALL.ps1').read_text(encoding='utf-8-sig')
    assert "-3 -c" not in text
    assert ".resolve-python-" in text


def test_prepare_piper_creates_short_ascii_espeak_alias_and_ready_marker():
    text = (ROOT / 'PREPARE_PIPER.ps1').read_text(encoding='utf-8-sig')
    assert 'subst.exe' in text
    assert 'piper-espeak-data-path.txt' in text
    assert 'piper-ready.json' in text
    assert 'PIPER_ESPEAK_DATA_DIR' in text
    assert "Test-Path -LiteralPath (Join-Path $aliasData 'phontab')" in text


def test_stop_removes_piper_subst_alias():
    text = (ROOT / 'STOP_ALL.ps1').read_text(encoding='utf-8-sig')
    assert 'piper-subst-drive.txt' in text
    assert 'subst.exe $drive /D' in text
