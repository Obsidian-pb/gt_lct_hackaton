import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import manage_users
from shared_auth import Accounts


class BootstrapAdminTests(unittest.TestCase):
    def test_first_launch_prompts_once_and_reuses_account(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ['manage_users.py', '--data-dir', directory, 'bootstrap-admin']
            output = io.StringIO()
            with patch.object(sys, 'argv', argv), patch.dict(os.environ, {'DATABASE_URL': ''}), \
                 patch.object(manage_users, 'getpass', side_effect=['safe-password-123', 'safe-password-123']) as prompt, \
                 contextlib.redirect_stdout(output):
                manage_users.main()
                manage_users.main()
            self.assertEqual(prompt.call_count, 2)
            accounts = Accounts(Path(directory))
            self.assertEqual(accounts.count(), 1)
            self.assertEqual(accounts.authenticate_credentials('admin', 'safe-password-123')['role'], 'admin')
            self.assertIn('уже существуют', output.getvalue())


if __name__ == '__main__':
    unittest.main()
