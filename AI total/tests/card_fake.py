"""Deterministic model responses for tests, never used by the application."""
from card_factory import GENERATED


def response(index=1):
    fields = {key: 'Неизвестно' for key in GENERATED}
    fields.update(country='Россия', city='Учебный город', street='Лесная', house=str(index),
                  address_text=f'Учебный город, Лесная, {index}', description='Дым из гаража.',
                  caller_name='Вымышленный заявитель', caller_role='Очевидец',
                  people='Возможно, человек внутри; не подтверждено', injured='Неизвестно',
                  phone_callback='Не указан', phone_scene='Не указан')
    return {'title': f'Карточка {index}: задымление гаража',
            'report': f'Лесная, дом {index}, дым из гаража. Муж заходил внутрь, я не видела, чтобы он вышел.',
            'fields': fields}


class FactoryFake:
    model = 'test-double'

    def __init__(self):
        self.calls = []
        self.failed = False

    def generate(self, system, payload, temperature=.3, schema=None):
        import time
        self.calls.append((system, payload, schema))
        if payload.get('operation') == 'card_caller':
            if payload['question'] == 'FAIL':
                raise RuntimeError('Тестовая ошибка заявителя')
            phone = any(word in payload['question'].lower() for word in ('телефон', 'перезвон', 'этому номеру'))
            return {'reply': 'Перезвоните на другой номер.' if phone else 'Муж заходил внутрь, я не видела, чтобы он вышел.', 'callback_requested': phone}
        if payload.get('operation') == 'card_reference':
            if 'REF_FAIL' in payload['report']:
                raise RuntimeError('Тестовая ошибка генерации эталона')
            return {'expected_fields': {key: {'value': 'Неизвестно', 'source_id': 0} for key in GENERATED},
                    'summary': 'Запишите известный адрес и сохраните неопределённость о людях.',
                    'classification_reason': 'Сверьте выбранные признаки с сообщением заявителя.',
                    'services_reason': 'Проверьте состав по классификатору и дополнительным признакам.',
                    'questions': ['Есть ли пострадавшие?'],
                    'critical_errors': ['Записать отсутствие людей, когда это не подтверждено.']}
        if payload.get('topic') == 'FAIL_ONCE' and payload['batch_position'] == 2 and not self.failed:
            self.failed = True
            raise RuntimeError('Тестовая недоступность модели')
        if payload.get('topic') == 'SLOW':
            time.sleep(.25)
        return response(payload.get('batch_position', 1))
