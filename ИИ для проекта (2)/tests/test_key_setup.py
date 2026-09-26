"""Exercise the Windows key writer with fake credentials, never the user's key."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('powershell.exe'), 'Windows PowerShell required')
class KeySetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='key setup тест ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / 'config.local.json'
        self.script = Path(__file__).resolve().parents[1] / 'setup_key.ps1'

    def run_writer(self, key):
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"
        entry = self.root / 'test.ps1'
        entry.write_text(
            '. ' + quote(self.script) + '\ntry {\n'
            + 'Save-GigaChatKey -Directory ' + quote(self.root) + ' -Key ' + quote(key)
            + ' | Out-Null\nexit 0\n} catch { exit 1 }\n', encoding='utf-8-sig')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(entry)], capture_output=True, timeout=20)
        self.assertNotIn(key.encode(), result.stdout + result.stderr)
        self.assertEqual(list(self.root.glob('.gigachat-config-*.tmp')), [])
        return result.returncode

    def test_first_key_is_saved_with_personal_defaults(self):
        self.assertEqual(self.run_writer('Basic ZHVtbXk6ZmFrZQ=='), 0)
        data = json.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual(data['authorization_key'], 'ZHVtbXk6ZmFrZQ==')
        self.assertEqual(data['scope'], 'GIGACHAT_API_PERS')
        self.assertTrue(data['verify_ssl'])

    def test_replacement_preserves_connection_settings(self):
        old = {'authorization_key': 'old', 'credentials': 'old-alias', 'model': 'ChosenModel',
               'scope': 'GIGACHAT_API_B2B', 'ca_bundle': 'C:/Сертификаты/root.pem',
               'verify_ssl': True, 'custom': {'name': 'Настройка'}}
        self.config.write_text(json.dumps(old, ensure_ascii=False), encoding='utf-8-sig')
        self.assertEqual(self.run_writer('new-test-key'), 0)
        actual = json.loads(self.config.read_text(encoding='utf-8'))
        expected = {**old, 'authorization_key': 'new-test-key'}
        del expected['credentials']
        self.assertEqual(actual, expected)

    def test_invalid_input_and_broken_config_never_overwrite(self):
        self.config.write_text('{"authorization_key":"keep"}', encoding='utf-8')
        before = self.config.read_bytes()
        for key in ('   ', 'bad key', 'bad\nkey'):
            with self.subTest(key=repr(key)):
                self.assertNotEqual(self.run_writer(key), 0)
                self.assertEqual(self.config.read_bytes(), before)
        self.config.write_text('{broken-json', encoding='utf-8')
        self.assertNotEqual(self.run_writer('new-test-key'), 0)
        self.assertEqual(self.config.read_text(encoding='utf-8'), '{broken-json')

    def test_interactive_entry_saves_key_and_calls_restart_without_leaking(self):
        helper = self.root / 'setup_key.ps1'
        shutil.copyfile(self.script, helper)
        (self.root / 'restart_ui.ps1').write_text(
            "$ok = (Test-Path -LiteralPath $env:AI_PROJECT_CONFIG) -and "
            "(!$env:GIGACHAT_CREDENTIALS) -and (!$env:FIRE_SIM_GIGACHAT_AUTHORIZATION_KEY)\n"
            "if (!$ok) { exit 8 }\n"
            "[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'restarted'), 'ok')\nexit 0\n",
            encoding='utf-8-sig')
        entry = self.root / 'interactive.ps1'
        entry.write_text(
            "function Read-Host { param([string]$Prompt, [switch]$AsSecureString)\n"
            "$secret = New-Object System.Security.SecureString; 'fake-interactive-key'.ToCharArray() | ForEach-Object { $secret.AppendChar($_) }; $secret\n}\n"
            "$env:GIGACHAT_CREDENTIALS='fake-old-key'\n"
            "$env:FIRE_SIM_GIGACHAT_AUTHORIZATION_KEY='fake-old-key'\n"
            "& (Join-Path $PSScriptRoot 'setup_key.ps1')\nexit $LASTEXITCODE\n",
            encoding='utf-8-sig')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(entry)], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode('utf-8', errors='replace'))
        self.assertNotIn(b'fake-interactive-key', result.stdout + result.stderr)
        self.assertEqual(json.loads(self.config.read_text())['authorization_key'], 'fake-interactive-key')
        self.assertTrue((self.root / 'restarted').is_file())


if __name__ == '__main__':
    unittest.main()
