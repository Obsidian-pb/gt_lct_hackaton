from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class AdminRoleUI(unittest.TestCase):
    def test_fallback_role_manager_is_served(self):
        html=(ROOT/'ui'/'react.html').read_text(encoding='utf-8')
        server=(ROOT/'web_ui.py').read_text(encoding='utf-8')
        script=(ROOT/'ui'/'admin-role-manager.js').read_text(encoding='utf-8')
        self.assertIn('/admin-role-manager.js',html)
        self.assertIn("'/admin-role-manager.js': ('admin-role-manager.js', 'text/javascript')",server)
        self.assertIn("api('training_role'",script)
        self.assertIn("dds: 'Диспетчер 112'",script)
        self.assertIn("operator: 'Оператор 112'",script)
        self.assertIn('это вы',script)

    def test_react_source_has_builtin_role_editor_for_future_rebuilds(self):
        source=(ROOT/'frontend'/'src'/'Admin.jsx').read_text(encoding='utf-8')
        self.assertIn('ADMIN_ROLE_EDITOR_BUILTIN=true',source)
        self.assertIn('TrainingParticipantsRoles',source)
        self.assertIn("api('training_role'",source)
        self.assertIn('Учебные роли в тренировках',source)

if __name__=='__main__':
    unittest.main()
