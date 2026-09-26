import copy
import tempfile
import unittest
from pathlib import Path
from ai_core import Engine
from card_factory import generate, approve, validate_content, LABELS, CATALOG
from card_fake import FactoryFake
from card_reference import generate as generate_reference
from web_ui import dispatch, make_server


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.provider = FactoryFake()

    def card(self):
        return generate(self.provider, {'category': 'fire', 'index': 2, 'total': 3})['content']

    def test_generated_card_complete_and_metadata_not_hallucinated(self):
        card = self.card()
        self.assertEqual(set(card['fields']), set(LABELS))
        self.assertEqual(card['fields']['latitude'], '')
        self.assertEqual(card['fields']['external_number'], '')
        self.assertEqual(card['fields']['controlled_by'], '')
        self.assertEqual(card['class_ids'], ['1010102'])
        self.assertEqual(card['fields']['injured'], 'Неизвестно')
        self.assertIn('Возможно', card['fields']['people'])
        self.assertIn('Не превращай', self.provider.calls[-1][0])

    def test_one_and_hundred_with_distinct_positions(self):
        first = generate(self.provider, {'index': 1, 'total': 1})
        last = generate(self.provider, {'index': 100, 'total': 100})
        self.assertNotEqual(first['content']['title'], last['content']['title'])
        for total in (0, 101, True, 2.5):
            with self.assertRaises(ValueError):
                generate(self.provider, {'total': total})
        with self.assertRaises(ValueError):
            generate(self.provider, {'total': 1, 'index': 2})

    def test_invalid_model_response_not_accepted(self):
        class Bad:
            def generate(self, *a, **kw):
                return {'title': 'Неполная карточка', 'fields': {}}
        with self.assertRaises(ValueError):
            generate(Bad(), {})

    def test_approval_requires_person_and_content_and_copies_snapshot(self):
        card = self.card()
        with self.assertRaises(ValueError):
            approve({'content': card, 'teacher': ' '})
        reference = generate_reference(self.provider, {'content': card})
        result = approve({'content': card, 'reference': reference, 'reference_checked': True, 'teacher': 'Преподаватель', 'note': 'Проверено'})
        card['fields']['house'] = '99'
        self.assertEqual(result['content']['fields']['house'], '2')
        for key in ('title', 'report'):
            bad = copy.deepcopy(card); bad[key] = ''
            with self.assertRaises(ValueError):
                approve({'content': bad, 'teacher': 'Преподаватель'})

    def test_unknown_class_and_invalid_coordinates(self):
        card = self.card()
        card['class_ids'] = ['official-invented-id']
        with self.assertRaises(ValueError):
            validate_content(card)
        card = self.card();card['fields'].update(latitude='91', longitude='0')
        with self.assertRaises(ValueError):
            validate_content(card)
        card['fields'].update(latitude='NaN', longitude='0')
        with self.assertRaises(ValueError):
            validate_content(card)
        card['fields'].update(latitude='55', longitude='37')
        validate_content(card)

    def test_no_card_files_written(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(self.provider, directory)
            card = dispatch(engine, 'card_generate', {'total': 1})['content']
            reference = dispatch(engine, 'card_reference', {'content': card})
            dispatch(engine, 'card_approve', {'content': card, 'reference': reference, 'reference_checked': True, 'teacher': 'Проверяющий'})
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_two_servers_cannot_share_port(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(self.provider, directory)
            server = make_server(engine, 0)
            try:
                with self.assertRaises(OSError):
                    make_server(engine, server.server_port)
            finally:
                server.server_close()


if __name__ == '__main__':
    unittest.main()
