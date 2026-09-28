from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UTF8_BOM = b'\xef\xbb\xbf'


def test_powershell_scripts_with_non_ascii_use_utf8_bom():
    """Windows PowerShell 5.1 treats BOM-less UTF-8 as ANSI on many PCs."""
    for path in ROOT.glob('*.ps1'):
        data = path.read_bytes()
        if any(byte >= 0x80 for byte in data):
            assert data.startswith(UTF8_BOM), f'{path.name} must be UTF-8 with BOM'
