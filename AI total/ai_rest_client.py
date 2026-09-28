"""Trusted server-to-server client for the dedicated AI REST dialogue service.

The browser never imports this module and never receives AI_REST_TOKEN or the
teacher-owned incident source.  The training backend is only a gateway: it adds
trusted card data and calls /v1/cards/replies on the separate AI process.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

REPLY_PATH = '/v1/cards/replies'
DEFAULT_BASE_URL = 'http://127.0.0.1:8890'
MAX_RESPONSE = 65536


def _settings():
    raw = (os.environ.get('AI_DIALOGUE_REST_URL') or os.environ.get('AI_REST_URL') or DEFAULT_BASE_URL).strip()
    parsed = urlsplit(raw)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or
            parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise RuntimeError('AI_DIALOGUE_REST_URL: укажите http(s)://host:port без пути, логина и параметров.')
    token = os.environ.get('AI_REST_TOKEN', '')
    if not isinstance(token, str) or len(token) < 24 or not token.isascii() or any(ch.isspace() for ch in token):
        raise RuntimeError('AI_REST_TOKEN не настроен для связи основного backend с выделенным ИИ REST API.')
    try:
        timeout = float(os.environ.get('AI_DIALOGUE_REST_TIMEOUT', '90'))
    except ValueError:
        raise RuntimeError('AI_DIALOGUE_REST_TIMEOUT должен быть числом секунд.') from None
    if not 1 <= timeout <= 300:
        raise RuntimeError('AI_DIALOGUE_REST_TIMEOUT должен быть от 1 до 300 секунд.')
    return raw.rstrip('/'), token, timeout


def _decode_json(raw, *, status=200):
    if len(raw) > MAX_RESPONSE:
        raise RuntimeError('Выделенный ИИ REST API вернул слишком большой ответ.')
    try:
        value = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeError, ValueError):
        raise RuntimeError('Выделенный ИИ REST API вернул некорректный JSON.') from None
    if status != 200:
        message = value.get('error', {}).get('message') if isinstance(value, dict) else None
        code = value.get('error', {}).get('code') if isinstance(value, dict) else None
        if status == 401:
            raise RuntimeError('Выделенный ИИ REST API отклонил AI_REST_TOKEN. Проверьте одинаковый токен на обоих серверах.')
        raise RuntimeError(f'Выделенный ИИ REST API вернул ошибку {status}' + (f' ({code})' if code else '') + (f': {message}' if message else '.'))
    if not isinstance(value, dict) or set(value) != {'reply'} or not isinstance(value['reply'], str) or not value['reply'].strip():
        raise RuntimeError('Выделенный ИИ REST API вернул ответ неверного формата: ожидается только {"reply":"..."}.')
    if len(value['reply']) > 1200:
        raise RuntimeError('Выделенный ИИ REST API вернул слишком длинную реплику.')
    return {'reply': value['reply'].strip()}


def caller_reply(*, card, student_fields, turns, question):
    """Ask the dedicated AI service for one stateless caller reply."""
    base, token, timeout = _settings()
    payload = json.dumps({
        'card': card,
        'student_fields': student_fields,
        'turns': turns,
        'question': question,
    }, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    request = Request(base + REPLY_PATH, data=payload, method='POST', headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/json',
        'Content-Type': 'application/json; charset=utf-8',
        'User-Agent': 'training-backend-ai-gateway/1.0',
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
            return _decode_json(raw, status=response.status)
    except HTTPError as exc:
        try:
            raw = exc.read(MAX_RESPONSE + 1)
        finally:
            exc.close()
        return _decode_json(raw, status=exc.code)
    except URLError as exc:
        reason = str(getattr(exc, 'reason', exc))
        raise RuntimeError('Нет связи с выделенным ИИ REST API. Проверьте AI_DIALOGUE_REST_URL, порт 8890 и запуск ai_rest_server.py. ' + reason) from None
    except TimeoutError:
        raise RuntimeError('Выделенный ИИ REST API не ответил вовремя.') from None


def health():
    """Check only the dedicated REST process; does not invoke the AI provider."""
    base, _, timeout = _settings()
    request = Request(base + '/health', method='GET', headers={'Accept': 'application/json'})
    try:
        with urlopen(request, timeout=min(timeout, 5)) as response:
            raw = response.read(8193)
        value = json.loads(raw.decode('utf-8-sig'))
        if response.status != 200 or value != {'status': 'ok'}:
            raise RuntimeError('неожиданный ответ health')
        return {'state': 'available', 'message': 'Выделенный ИИ REST API доступен.', 'base_url': base}
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc).startswith('AI_'):
            raise
        raise RuntimeError('Выделенный ИИ REST API недоступен: ' + str(exc)) from None
