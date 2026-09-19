import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import provider
from provider import GigaChat


class ProviderConfigTests(unittest.TestCase):
    def _write(self, directory, name, key, model='pro'):
        Path(directory, name).write_text(json.dumps({
            'authorization_key': key,
            'scope': 'GIGACHAT_API_PERS',
            'model': model,
            'verify_ssl': True,
            'base_url': 'https://api.giga.chat/v1',
        }), encoding='utf-8')

    def test_team_config_is_used_after_clone(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, 'config.team.json', 'TEAM_KEY')
            fake_provider = str(Path(td, 'provider.py'))
            with patch.object(provider, '__file__', fake_provider), patch.dict(os.environ, {
                'APPDATA': str(Path(td, 'empty-appdata')),
                'AI_PROJECT_CONFIG': '',
                'FIRE_SIM_GIGACHAT_CONFIG': '',
                'GIGACHAT_CREDENTIALS': '',
                'FIRE_SIM_GIGACHAT_AUTHORIZATION_KEY': '',
            }, clear=False):
                client = GigaChat()
            self.assertEqual(client.key, 'TEAM_KEY')

    def test_local_config_overrides_team_config(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, 'config.team.json', 'TEAM_KEY')
            self._write(td, 'config.local.json', 'LOCAL_KEY')
            fake_provider = str(Path(td, 'provider.py'))
            with patch.object(provider, '__file__', fake_provider), patch.dict(os.environ, {
                'APPDATA': str(Path(td, 'empty-appdata')),
                'AI_PROJECT_CONFIG': '',
                'FIRE_SIM_GIGACHAT_CONFIG': '',
                'GIGACHAT_CREDENTIALS': '',
                'FIRE_SIM_GIGACHAT_AUTHORIZATION_KEY': '',
            }, clear=False):
                client = GigaChat()
            self.assertEqual(client.key, 'LOCAL_KEY')


if __name__ == '__main__':
    unittest.main()
