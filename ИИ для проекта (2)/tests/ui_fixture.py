"""Browser test server with a fake provider and a disposable exercise directory."""
import tempfile
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path('tests').resolve()))
from card_fake import FactoryFake
from ai_core import Engine, FIELDS
from web_ui import make_server


class FakeProvider:
    def __init__(self):
        self.factory = FactoryFake()

    def generate(self, system, payload, temperature=.3, schema=None):
        if 'incident_class' in payload or payload.get('operation') in ('card_reference', 'card_caller'):
            return self.factory.generate(system, payload, temperature, schema)
        if 'reference' in payload:
            return {'summary': 'Проверьте сведения о людях внутри.', 'fields': {key: {'verdict': 'partial', 'comment': 'Нужно уточнение.', 'clarification': 'Сохраните неопределённость.', 'evidence': []} for key in payload.get('field_labels', FIELDS)}}
        if 'delivered_message' in payload:
            return {'reply': 'Назовите точный адрес происшествия.'}
        if 'known' in payload:
            return {'reply': 'Муж заходил в гараж. Я не видела, чтобы он вышел.'}
        if 'field_labels' in payload and 'history' in payload:
            return {'hint': 'Уточните адрес у заявителя.'}
        if 'topic' in payload and 'field_labels' in payload:
            task = json.loads(Path('sample.json').read_text(encoding='utf-8'))
            return {k: task[k] for k in ('title', 'opening', 'persona', 'fields')}
        raise RuntimeError('Неожиданный тестовый запрос')


with tempfile.TemporaryDirectory() as folder:
    server = make_server(Engine(FakeProvider(), folder), 0)
    print(f'http://127.0.0.1:{server.server_port}', flush=True)
    server.serve_forever()
