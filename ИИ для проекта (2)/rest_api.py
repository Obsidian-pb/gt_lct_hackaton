"""HTTP-independent REST router. Business operations live in application.py."""
from contextlib import nullcontext
from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from api_contract import PREFIX, ROUTES, COMMON, input_schema
from application import dispatch

ROOT = Path(__file__).resolve().parent


class APIError(Exception):
    def __init__(self, status, code, message, *, details=None, headers=None):
        self.status, self.code, self.message = status, code, message
        self.details, self.headers = details, headers or {}
        super().__init__(message)

    def body(self, request_id):
        error = {'code': self.code, 'message': self.message}
        if self.details:
            error['details'] = self.details
        return {'error': error, 'request_id': request_id}


@dataclass
class APIResponse:
    data: object
    status: int = 200
    headers: dict = field(default_factory=dict)


def validate(value, schema, name):
    expected = schema.get('type')
    valid_type = {'object': lambda x: isinstance(x, dict), 'array': lambda x: isinstance(x, list),
                  'integer': lambda x: type(x) is int, 'string': lambda x: isinstance(x, str),
                  'boolean': lambda x: type(x) is bool}
    if expected in valid_type and not valid_type[expected](value):
        raise APIError(422, 'invalid_field', f'Поле {name}: неверный тип данных.', details={'field': name, 'type': expected})
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', 256000):
            raise APIError(422, 'invalid_field', f'Поле {name}: недопустимая длина.')
        if schema.get('pattern') and not re.fullmatch(schema['pattern'], value):
            raise APIError(422, 'invalid_field', f'Поле {name}: неверный формат.')
    if expected == 'integer' and not schema.get('minimum', value) <= value <= schema.get('maximum', value):
        raise APIError(422, 'invalid_field', f'Поле {name}: значение вне допустимого диапазона.')
    if 'enum' in schema and value not in schema['enum']:
        raise APIError(422, 'invalid_field', f'Поле {name}: неизвестное значение.')
    if isinstance(value, list) and 'items' in schema:
        for item in value:
            validate(item, schema['items'], name)
    if isinstance(value, dict) and isinstance(schema.get('additionalProperties'), dict):
        for item in value.values():
            validate(item, schema['additionalProperties'], name)


@lru_cache(maxsize=2)
def geo_file(name):
    return json.loads((ROOT / 'ui' / 'geo' / name).read_text(encoding='utf-8'))


class RestAPI:
    def __init__(self, engine, lock):
        self.engine, self.lock = engine, lock
        self.speech_lock = threading.Lock()
        self.routes = [(r, re.compile('^' + re.sub(r'\{\w+\}', '([^/]+)', PREFIX + r.path) + '/?$')) for r in ROUTES]

    def resolve(self, method, target):
        parsed = urlsplit(target)
        matches = [(r, rx.fullmatch(parsed.path)) for r, rx in self.routes]
        matches = [(r, m) for r, m in matches if m]
        if not matches:
            raise APIError(404, 'not_found', 'Маршрут API не найден.')
        allowed = {r.method for r, _ in matches} | {'OPTIONS'}
        if 'GET' in allowed:
            allowed.add('HEAD')
        allow = sorted(allowed)
        for route, match in matches:
            if method == route.method:
                return route, dict(zip(route.parameters, (unquote(v, errors='strict') for v in match.groups())))
        raise APIError(405, 'method_not_allowed', 'HTTP-метод не поддерживается для этого ресурса.', headers={'Allow': ', '.join(allow)})

    def allowed_methods(self, target):
        path = urlsplit(target).path
        methods = {r.method for r, rx in self.routes if rx.fullmatch(path)}
        if not methods:
            raise APIError(404, 'not_found', 'Маршрут API не найден.')
        return sorted(methods | {'OPTIONS'} | ({'HEAD'} if 'GET' in methods else set()))

    def payload(self, route, path_values, target, body):
        raw_query = parse_qs(urlsplit(target).query, keep_blank_values=True, max_num_fields=30, strict_parsing=True)
        if route.method == 'GET':
            data = {}
            for name, values in raw_query.items():
                if len(values) != 1:
                    raise APIError(400, 'ambiguous_query', 'Параметр запроса не должен повторяться.')
                value = values[0]
                kind = COMMON.get(name, {}).get('type')
                if kind == 'boolean':
                    if value not in ('true', 'false'):
                        raise APIError(422, 'invalid_field', f'Параметр {name}: укажите true или false.')
                    value = value == 'true'
                elif kind == 'integer':
                    if not re.fullmatch(r'\d+', value):
                        raise APIError(422, 'invalid_field', f'Параметр {name}: требуется целое число.')
                    value = int(value)
                data[name] = value
        else:
            if raw_query:
                raise APIError(400, 'unexpected_query', 'Параметры этой операции передаются в JSON-теле.')
            if not isinstance(body, dict):
                raise APIError(400, 'invalid_json', 'Тело запроса должно быть JSON-объектом.')
            data = dict(body)
        if any(name in data for name in (*route.parameters, 'action', 'operation')):
            raise APIError(400, 'ambiguous_payload', 'Идентификатор и операция задаются адресом ресурса.')
        schema = input_schema(route)
        missing = [n for n in route.required if n not in data]
        if missing:
            raise APIError(422, 'missing_fields', 'Не заполнены обязательные поля.', details={'fields': missing})
        if not route.extensible and set(data) - set(schema['properties']):
            raise APIError(422, 'unknown_fields', 'Запрос содержит неизвестные поля.')
        for name, value in data.items():
            validate(value, schema['properties'].get(name, COMMON.get(name, {})), name)
        for name, value in path_values.items():
            validate(value, COMMON[name], name)
            if name == 'student' and not value.strip():
                raise APIError(422, 'invalid_field', 'Укажите имя обучающегося.')
            if name == 'id':
                expected = 't-' if route.path.startswith('/tasks/') else 's-'
                if not value.startswith(expected):
                    raise APIError(422, 'invalid_field', 'Идентификатор относится к другому типу ресурса.')
        data.update(path_values)
        if route.operation:
            data['operation'] = route.operation
        return data

    def check_state(self, route, p):
        if 'id' not in route.parameters:
            return
        current = self.engine.load(p['id'])
        if route.action == 'student_action' and current.get('student') != p['student']:
            raise APIError(403, 'wrong_student', 'Эта тренировка относится к другому обучающемуся.')
        if route.method == 'GET':
            return
        if route.action == 'save_task' and current['status'] != 'draft':
            raise APIError(409, 'state_conflict', 'Изменять можно только черновик задания.')
        active_actions = {'ask','hint','save_card','submit','connect','channel','teacher_finish'}
        action = route.operation or route.action
        if action in active_actions | {'nudge'} and current['status'] != 'active':
            raise APIError(409, 'state_conflict', 'Работа не активна: завершена или ожидает предыдущую карточку.')

    def handle(self, method, target, body=None):
        try:
            route, path_values = self.resolve(method, target)
            payload = self.payload(route, path_values, target, body)
            with self.lock if route.storage else self.speech_lock if route.action == 'tts_synthesize' else nullcontext():
                self.check_state(route, payload)
                if route.action == 'geo_map':
                    result = geo_file('map.json')
                elif route.action == 'geo_addresses':
                    source = geo_file('addresses.json')
                    result = source
                    if 'q' in payload or 'limit' in payload:
                        words = re.findall(r'[\w]+', payload.get('q', '').lower().replace('ё','е'))
                        matches = [row for row in source['addresses'] if all(word in (row.get('street','')+' '+row.get('house','')).lower().replace('ё','е') for word in words)]
                        limit = payload.get('limit', 20)
                        result = {**source, 'addresses': matches[:limit], 'total': len(matches), 'limit': limit}
                elif route.action == 'training_callback':
                    import curriculum
                    result = curriculum.callback(self.engine,payload['resource_id'],payload['card_id'],payload['student'],payload['question'],payload.get('source','text'),payload['call_id'],self.lock)
                else:
                    result = dispatch(self.engine, route.action, payload)
            headers = {}
            if route.status == 201 and isinstance(result, dict) and result.get('id'):
                resource = '/trainings/' if result['id'].startswith('training-') else '/scenarios/' if result['id'].startswith('scenario-') else '/tasks/' if result['id'].startswith('t-') else '/sessions/'
                headers['Location'] = PREFIX + resource + result['id']
            return APIResponse(result, route.status, headers)
        except APIError:
            raise
        except FileNotFoundError:
            raise APIError(404, 'not_found', 'Данные не найдены.') from None
        except (ValueError, KeyError, TypeError) as exc:
            message = str(exc) if isinstance(exc, ValueError) else 'Данные имеют неверный формат.'
            raise APIError(422, 'validation_error', message) from None
        except RuntimeError as exc:
            raise APIError(502, 'provider_error', str(exc)) from None
