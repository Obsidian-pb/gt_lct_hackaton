"""Small, stateless HTTP API for generating a draft incident card with AI.

This process deliberately has no Engine, database or publishing operations.
"""
from __future__ import annotations

import argparse
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import threading
from urllib.parse import parse_qsl
import uuid

import card_factory
import ai_dialogue
from provider import AIProvider

PATH = '/v1/cards/generations'
REPLY_PATH = '/v1/cards/replies'
FIELDS = {'topic', 'category', 'classification', 'flags', 'location',
          'recent_titles', 'index', 'total', 'format'}


def as_text(card):
    """Render the *same* generated card as readable UTF-8, without another AI call."""
    lines = [card['title'], '', 'Сообщение заявителя:', card['report'], '', 'Поля карточки:']
    for key, label in card_factory.LABELS.items():
        value = card['fields'][key]
        if value.strip():
            lines.append(f'{label}: {value}')
    lines.extend(['', 'Коды происшествия: ' + ', '.join(card['class_ids']),
                  'Службы: ' + ', '.join(f'{code} — {card_factory.SERVICES[code]}' for code in card['services']),
                  'Главная служба: ' + (card['main_service'] or 'Не определена')])
    return '\n'.join(lines) + '\n'


def generate(provider, body):
    if not isinstance(body, dict) or set(body) - FIELDS:
        raise ValueError('Передайте JSON-объект только с параметрами генерации карточки.')
    output = body.get('format', 'json')
    if output not in ('json', 'text'):
        raise ValueError('format должен быть json или text.')
    card = card_factory.generate(provider, {k: v for k, v in body.items() if k != 'format'})['content']
    return (as_text(card), 'text/plain; charset=utf-8') if output == 'text' else (card, 'application/json; charset=utf-8')


def _unique_object(pairs):
    """Reject duplicate JSON keys at any nesting level."""
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Повторный ключ JSON: ' + str(key)[:80])
        value[key] = item
    return value


def parse_form(pairs):
    """Decode native HTML field names into the same request as JSON fetch()."""
    data, fields = {}, {}
    for name, value in pairs:
        if name.startswith(('student_fields[', 'fields[')) and name.endswith(']'):
            key = name[name.index('[') + 1:-1]
            if key not in ai_dialogue.LEARNER_FIELDS or key in fields:
                raise ValueError('Неизвестное или повторное поле обучающегося.')
            fields[key] = value
        elif name.startswith('student_fields.'):
            key = name.removeprefix('student_fields.')
            if key not in ai_dialogue.LEARNER_FIELDS or key in fields:
                raise ValueError('Неизвестное или повторное поле обучающегося.')
            fields[key] = value
        elif name in ai_dialogue.LEARNER_FIELDS:
            if name in fields:
                raise ValueError('Повторное поле обучающегося.')
            fields[name] = value
        elif name in {'card', 'incident_report', 'student_fields', 'turns', 'question', 'format'}:
            if name in data:
                raise ValueError('Повторное поле формы.')
            data[name] = value
        else:
            raise ValueError('Неизвестное поле формы: ' + name[:80])
    for key in ('card', 'turns', 'student_fields'):
        if key in data:
            try:
                data[key] = json.loads(data[key],
                                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                                       object_pairs_hook=_unique_object)
            except (ValueError, TypeError):
                raise ValueError('Поле ' + key + ' должно быть корректным JSON.') from None
    if fields:
        if 'student_fields' in data:
            raise ValueError('Укажите поля обучающегося одним способом.')
        data['student_fields'] = fields
    return data


def parse_multipart(raw, content_type):
    if 'boundary=' not in content_type.lower():
        raise ValueError('В multipart/form-data отсутствует boundary.')
    message = BytesParser(policy=policy.default).parsebytes(
        b'Content-Type: ' + content_type.encode('ascii') + b'\r\nMIME-Version: 1.0\r\n\r\n' + raw)
    if not message.is_multipart():
        raise ValueError('Некорректная multipart форма.')
    parts = list(message.iter_parts())
    if len(parts) > 100:
        raise ValueError('В форме слишком много полей.')
    pairs = []
    for part in parts:
        if part.get_content_disposition() != 'form-data' or part.get_filename() is not None:
            raise ValueError('Файлы и вложения в этой форме не принимаются.')
        name = part.get_param('name', header='content-disposition')
        if not isinstance(name, str):
            raise ValueError('У поля формы отсутствует имя.')
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            raise ValueError('Некорректное текстовое поле формы.')
        try:
            pairs.append((name, payload.decode('utf-8-sig')))
        except UnicodeError:
            raise ValueError('Текст формы должен быть в UTF-8.') from None
    return parse_form(pairs)


def caller_reply(provider, body):
    if not isinstance(body, dict):
        raise ValueError('Передайте объект с карточкой и вопросом.')
    output = body.get('format', 'json')
    if output not in ('json', 'text'):
        raise ValueError('format должен быть json или text.')
    result = ai_dialogue.ask(provider, {k: v for k, v in body.items() if k != 'format'})
    return (result['reply'], 'text/plain; charset=utf-8') if output == 'text' else (result, 'application/json; charset=utf-8')


def openapi():
    return {
        'openapi': '3.1.0',
        'info': {'title': 'ИИ: генерация карточки и ответ заявителя', 'version': '1.3.0',
                 'description': 'Сервис не сохраняет карточки, поля обучающегося и историю разговора.'},
        'servers': [{'url': 'http://127.0.0.1:8890'}],
        'paths': {
            '/health': {'get': {'summary': 'Проверка процесса без обращения к ИИ',
                                'responses': {'200': {'description': 'Сервер запущен'}}}},
            PATH: {'post': {'summary': 'Сгенерировать одну учебную карточку',
                            'security': [{'ApiToken': []}],
                            'requestBody': {'required': True, 'content': {'application/json': {'schema': {
                                'type': 'object', 'additionalProperties': False,
                                'properties': {
                                    'topic': {'type': 'string', 'maxLength': 3000},
                                    'category': {'type': 'string', 'description': 'Группа из классификатора; по умолчанию mixed'},
                                    'classification': {'type': 'object', 'description': 'Признаки sign1, sign2, sign3 или id'},
                                    'flags': {'type': 'object', 'description': 'Дополнительные признаки yes/no/unknown'},
                                    'location': {'type': 'string', 'maxLength': 160},
                                    'recent_titles': {'type': 'array', 'maxItems': 10, 'items': {'type': 'string'}},
                                    'index': {'type': 'integer', 'minimum': 1, 'maximum': 100},
                                    'total': {'type': 'integer', 'minimum': 1, 'maximum': 100},
                                    'format': {'type': 'string', 'enum': ['json', 'text'], 'default': 'json'},
                                }}}}},
                            'responses': {
                                '200': {'description': 'Черновик без записи в хранилище', 'content': {
                                    'application/json': {'schema': {'type': 'object', 'description': 'Объект карточки: title, report, fields, class_ids, services, main_service, flags'}},
                                    'text/plain': {'schema': {'type': 'string'}}}},
                                '400': {'description': 'Некорректный JSON или параметры'},
                                '401': {'description': 'Неверный токен интеграции'},
                                '413': {'description': 'Слишком большой запрос'},
                                '415': {'description': 'Нужен application/json'},
                                '422': {'description': 'Некорректные параметры карточки'},
                                '502': {'description': 'Ошибка провайдера ИИ'},
                            }}},
            REPLY_PATH: {'post': {'summary': 'Ответ заявителя на произвольный вопрос обучающегося',
                                 'security': [{'ApiToken': []}],
                                 'requestBody': {'required': True, 'content': {
                                     'application/json': {'schema': {'$ref': '#/components/schemas/ReplyRequest'}},
                                     'application/x-www-form-urlencoded': {'schema': {'$ref': '#/components/schemas/ReplyRequest'}},
                                     'multipart/form-data': {'schema': {'$ref': '#/components/schemas/ReplyRequest'}}}},
                                 'responses': {'200': {'description': 'Ответ заявителя без изменения карточки', 'content': {
                                     'application/json': {'schema': {'type': 'object', 'properties': {'reply': {'type': 'string'}}}},
                                     'text/plain': {'schema': {'type': 'string'}}}},
                                     '401': {'description': 'Неверный токен интеграции'},
                                     '413': {'description': 'Слишком большой запрос'},
                                     '422': {'description': 'Некорректные поля или история'},
                                     '502': {'description': 'Ошибка провайдера ИИ'}}}},
        },
        'components': {'securitySchemes': {'ApiToken': {'type': 'http', 'scheme': 'bearer',
                         'description': 'AI_REST_TOKEN; не ключ AITUNNEL.'}},
                       'schemas': {'ReplyRequest': {'type': 'object', 'required': ['question'],
                           'oneOf': [{'required': ['card']}, {'required': ['incident_report']}],
                           'description': 'Передайте card (полную преподавательскую карточку) или incident_report из доверенного серверного контура. При card исходное сообщение имеет приоритет, а доверенные поля карточки могут дополнять его. student_fields — только записи обучающегося. В HTML форме card, turns и student_fields передаются JSON-строками либо поля student_fields[city].',
                           'additionalProperties': False,
                           'properties': {
                               'card': {'type': 'object'}, 'incident_report': {'type': 'string', 'maxLength': 6000},
                               'student_fields': {'type': 'object', 'additionalProperties': {'type': 'string'}},
                               'question': {'type': 'string', 'maxLength': 2000},
                               'turns': {'type': 'array', 'maxItems': 100, 'items': {'type': 'object'}},
                               'format': {'type': 'string', 'enum': ['json', 'text'], 'default': 'json'},
                           }}}},
    }


def make_server(provider, port=8890, *, token, host='127.0.0.1'):
    if not isinstance(token, str) or len(token) < 24 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError('AI_REST_TOKEN должен содержать не менее 24 символов ASCII без пробелов.')
    model_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not put prompts, URLs or credentials into console logs.

        def reply(self, status, data, content_type='application/json; charset=utf-8'):
            payload = data.encode('utf-8') if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Request-ID', self.request_id)
            self.end_headers()
            self.wfile.write(payload)

        def fail(self, status, code, message):
            self.reply(status, {'error': {'code': code, 'message': message}, 'request_id': self.request_id})

        def do_GET(self):
            self.request_id = uuid.uuid4().hex
            if self.path == '/health':
                self.reply(200, {'status': 'ok'})
            elif self.path == '/openapi.json':
                self.reply(200, openapi())
            else:
                self.fail(404, 'not_found', 'Маршрут не найден.')

        def do_POST(self):
            self.request_id = uuid.uuid4().hex
            if self.path not in (PATH, REPLY_PATH):
                self.fail(404, 'not_found', 'Маршрут не найден.'); return
            auth = self.headers.get('Authorization', '')
            if not secrets.compare_digest(auth, 'Bearer ' + token):
                self.fail(401, 'unauthorized', 'Требуется отдельный токен AI_REST_TOKEN.'); return
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                self.fail(400, 'invalid_length', 'Укажите один Content-Length без Transfer-Encoding.'); return
            try:
                size = int(self.headers['Content-Length'])
            except ValueError:
                self.fail(400, 'invalid_length', 'Некорректный Content-Length.'); return
            limit = 16000 if self.path == PATH else 256000
            if size < 1 or size > limit:
                self.fail(413 if size > limit else 400, 'invalid_length', f'Размер запроса должен быть от 1 до {limit} байт.'); return
            mime = self.headers.get_content_type()
            if mime != 'application/json' and (self.path != REPLY_PATH or mime not in ('application/x-www-form-urlencoded', 'multipart/form-data')):
                self.fail(415, 'unsupported_media_type', 'Для ответа заявителя используйте JSON, HTML форму или FormData.'); return
            try:
                raw = self.rfile.read(size)
                if mime == 'application/json':
                    data = json.loads(raw.decode('utf-8-sig'),
                                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                                      object_pairs_hook=_unique_object)
                elif mime == 'application/x-www-form-urlencoded':
                    pairs = parse_qsl(raw.decode('utf-8'), keep_blank_values=True, strict_parsing=True,
                                      max_num_fields=100, encoding='utf-8', errors='strict')
                    data = parse_form(pairs)
                else:
                    data = parse_multipart(raw, self.headers.get('Content-Type', ''))
            except (ValueError, UnicodeError, RecursionError):
                self.fail(400, 'invalid_body', 'Некорректный JSON или поля формы UTF-8.'); return
            try:
                # The provider can maintain a mutable OAuth token and selected model.
                with model_lock:
                    result, response_mime = (generate(provider, data) if self.path == PATH else caller_reply(provider, data))
                self.reply(200, result, response_mime)
            except ValueError as exc:
                self.fail(422, 'invalid_card', str(exc))
            except RuntimeError as exc:
                self.fail(502, 'provider_error', str(exc))
            except Exception:
                self.fail(500, 'internal_error', 'Не удалось обработать запрос.')

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description='REST API для генерации карточек и учебного диалога с заявителем')
    parser.add_argument('--port', type=int, default=8890)
    parser.add_argument('--host', default='127.0.0.1', help='Адрес прослушивания; для отдельной машины обычно 0.0.0.0')
    args = parser.parse_args()
    token = os.environ.get('AI_REST_TOKEN', '')
    if not 1 <= args.port <= 65535:
        parser.error('Порт должен быть в диапазоне 1–65535.')
    if len(token) < 24:
        parser.error('Задайте AI_REST_TOKEN (отдельный токен от 24 символов, не ключ AITUNNEL).')
    server = make_server(AIProvider(), args.port, token=token, host=args.host)
    shown_host = '127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host
    print(f'ИИ REST API: http://{shown_host}:{server.server_port}  (listen={args.host}; карточки: {PATH}; диалог: {REPLY_PATH})', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
