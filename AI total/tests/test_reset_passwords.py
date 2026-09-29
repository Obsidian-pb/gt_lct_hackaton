import unittest
from unittest.mock import patch

import auth_service
from auth_crypto import verify_password


class ResetPasswordsTests(unittest.TestCase):
    def setUp(self):
        self.repository = patch('auth_service.auth_repository.AuthRepository').start().return_value
        self.addCleanup(patch.stopall)
        self.repository.list_students_by_ids.return_value = [
            {'id': 7, 'login': 'student7', 'full_name': 'Ученик Семь',
             'display_name': 'Семь', 'role': 'student'}]
        self.repository.list_students_in_group.return_value = [
            {'id': 7, 'login': 'student7', 'full_name': 'Ученик Семь',
             'display_name': 'Семь', 'role': 'student'}]

    def test_generated_password_is_returned_once_and_only_hash_is_stored(self):
        result = auth_service.reset_passwords(user_ids=[7])
        self.assertEqual(result[0]['user_id'], 7)
        self.assertEqual(result[0]['login'], 'student7')
        self.assertEqual(result[0]['display_name'], 'Семь')
        password = result[0]['password']
        stored_hash = self.repository.set_password.call_args.args[1]
        self.assertNotEqual(stored_hash, password)
        self.assertTrue(verify_password(password, stored_hash))

    def test_shared_password_and_group_selection(self):
        result = auth_service.reset_passwords(group_id=13, password='one-time')
        self.repository.list_students_in_group.assert_called_once_with(13)
        self.assertEqual(result[0]['password'], 'one-time')
        self.assertTrue(verify_password(
            'one-time', self.repository.set_password.call_args.args[1]))

    def test_rejects_invalid_selection_and_unknown_students(self):
        with self.assertRaises(auth_service.AuthError):
            auth_service.reset_passwords()
        self.repository.list_students_by_ids.return_value = []
        with self.assertRaises(auth_service.AuthError):
            auth_service.reset_passwords(user_ids=[7])

    def test_rejects_short_password(self):
        with self.assertRaises(auth_service.AuthError):
            auth_service.reset_passwords(user_ids=[7], password='short')


if __name__ == '__main__':
    unittest.main()
