import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from ai_core import Engine
from test_core import Fake
from ui_release import release_id, validate_ui, compatible_server
from web_ui import make_server, UI_REVISION, ROOT


class ReleaseTests(unittest.TestCase):
    def test_old_process_is_not_reused_just_because_its_folder_matches(self):
        old = {'app': 'ai-project-ui', 'root': str(ROOT)}
        self.assertFalse(compatible_server(old, ROOT, UI_REVISION))
        current = old | {'revision': UI_REVISION, 'pages': ['/student']}
        self.assertTrue(compatible_server(current, ROOT, UI_REVISION))
        for patch in ({'revision': 'old'}, {'root': 'another copy'}, {'pages': ['/teacher']}):
            self.assertFalse(compatible_server(current | patch, ROOT, UI_REVISION))

    def test_revision_tracks_code_and_ui_but_not_credentials_or_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'ui').mkdir()
            (root / 'ui' / 'student.css').write_text('first')
            before = release_id(root)
            (root / 'config.local.json').write_text('private')
            (root / 'data').mkdir()
            (root / 'data' / 's-test.json').write_text('student work')
            self.assertEqual(before, release_id(root))
            (root / 'ui' / 'student.css').write_text('updated')
            self.assertNotEqual(before, release_id(root))
            with self.assertRaisesRegex(RuntimeError, 'неполная копия'):
                validate_ui(root)

    def test_student_route_and_assets_are_served_from_clean_distribution(self):
        validate_ui()
        with tempfile.TemporaryDirectory() as directory:
            server = make_server(Engine(Fake(), directory), 0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with urllib.request.urlopen(base + '/health') as response:
                    health = json.load(response)
                self.assertTrue(compatible_server(health, ROOT, UI_REVISION))
                self.assertGreater(health['pid'], 0)
                for path in ('/student', '/student/', '/student?from=login'):
                    with urllib.request.urlopen(base + path) as response:
                        self.assertIn('text/html', response.headers['Content-Type'])
                        body = response.read().decode()
                        self.assertIn('student-app', body)
                        self.assertIn('/student.css', body)
                        self.assertIn('/react/app.js', body)
                for path in ('/student.css', '/theme.css', '/react/app.js'):
                    with urllib.request.urlopen(base + path) as response:
                        self.assertEqual(response.status, 200)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=2)
