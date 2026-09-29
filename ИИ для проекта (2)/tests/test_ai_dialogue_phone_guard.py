import unittest

from ai_dialogue import _grounding_issue, _known_phones


class PhoneGuardTests(unittest.TestCase):
    def test_phone_is_not_merged_with_digits_on_previous_line(self):
        trusted = 'Дым из окна 3 этажа.\n+7 (913) 555-12-34'
        self.assertEqual(_known_phones(trusted), {'9135551234'})
        self.assertIsNone(_grounding_issue('8 913 555-12-34', {}, trusted))


if __name__ == '__main__':
    unittest.main()
