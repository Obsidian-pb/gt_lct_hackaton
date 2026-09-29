from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AdminSelfLearnerUiTests(unittest.TestCase):
    def test_admin_account_seeds_separate_learner_profile_in_source(self):
        source = (ROOT / 'frontend' / 'src' / 'admin-auth.js').read_text(encoding='utf-8')
        self.assertIn("linked_admin_login:account.login", source)
        self.assertIn("role:'Обучающийся'", source)
        self.assertIn('training_profile:true', source)

    def test_bundled_ui_bootstraps_admin_learner_before_react(self):
        html = (ROOT / 'ui' / 'react.html').read_text(encoding='utf-8')
        self.assertIn("linked_admin_login:a.login", html)
        self.assertIn("role:'Обучающийся'", html)
        self.assertLess(html.index('linked_admin_login:a.login'), html.index('/react/app.js'))

    def test_fallback_role_manager_can_enroll_admin_as_dispatcher(self):
        source = (ROOT / 'ui' / 'admin-role-manager.js').read_text(encoding='utf-8')
        self.assertIn("api('training_add_participants'", source)
        self.assertIn("api('training_role'", source)
        self.assertIn("v==='dds'?'selected':''", source)
        self.assertIn('Добавить себя', source)
        self.assertNotIn('if(globalThis.ADMIN_ROLE_EDITOR_BUILTIN) return;', source)

    def test_react_source_has_same_capability_for_future_rebuilds(self):
        source = (ROOT / 'frontend' / 'src' / 'Admin.jsx').read_text(encoding='utf-8')
        self.assertIn('function AddUserToTraining', source)
        self.assertIn('Учебный профиль администратора', source)
        self.assertIn("user.linked_admin_login?'dds':'operator'", source)


if __name__ == '__main__':
    unittest.main()
