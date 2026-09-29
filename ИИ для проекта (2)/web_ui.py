"""Local single-user browser client for the independent training engine."""
import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import json
import ipaddress
from pathlib import Path
import re
import secrets
import socket
import threading
import urllib.request
import time
from urllib.parse import urlsplit, parse_qs, quote
import webbrowser
from datetime import datetime

from ai_core import Engine
from provider import AIProvider
from ui_release import release_id, validate_ui, compatible_server
from api_contract import PREFIX, openapi
from rest_api import APIError, RestAPI
from shared_auth import Accounts, check_action
from database import store_from_url
import uuid

ROOT = Path(__file__).resolve().parent
ADMIN_RESET_TOKEN_PATH = ROOT / '.runtime' / 'admin-reset-token.txt'
ADMIN_RESET_TTL_SECONDS = 600

def _valid_admin_reset_token(candidate, *, consume=False):
    if not isinstance(candidate, str) or len(candidate) < 32 or len(candidate) > 256:
        return False
    try:
        path = ADMIN_RESET_TOKEN_PATH
        stat = path.stat()
        if time.time() - stat.st_mtime > ADMIN_RESET_TTL_SECONDS:
            path.unlink(missing_ok=True)
            return False
        expected = path.read_text(encoding='ascii').strip()
        ok = bool(expected) and secrets.compare_digest(candidate.encode('ascii'), expected.encode('ascii'))
        if ok and consume:
            path.unlink(missing_ok=True)
        return ok
    except (OSError, UnicodeError, UnicodeEncodeError):
        return False

def _admin_reset_page(token):
    token_json = json.dumps(token, ensure_ascii=True)
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Сброс администратора · 112</title>
<style>body{{font-family:Inter,Segoe UI,Arial,sans-serif;background:#f3f6fa;margin:0;min-height:100vh;display:grid;place-items:center;color:#172033}}main{{width:min(560px,calc(100% - 32px));background:#fff;border:1px solid #d9e1ec;border-radius:18px;padding:30px;box-shadow:0 16px 50px #1720331a}}h1{{margin:0 0 12px}}p{{line-height:1.55}}.note{{background:#f6f8fb;border-radius:12px;padding:14px}}button{{width:100%;margin-top:18px;padding:13px;border:0;border-radius:10px;background:#b42318;color:#fff;font-weight:700;font-size:16px;cursor:pointer}}button:disabled{{opacity:.55}}#status{{margin-top:14px;font-weight:600}}</style></head>
<body><main><h1>Сброс администратора</h1><p>Будут удалены только локальные данные входа администратора в этом браузере.</p><p class="note"><b>Не удаляются:</b> карточки, сценарии, тренировки, результаты, пользователи и учебные роли.</p><button id="reset">Сбросить администратора</button><div id="status"></div></main>
<script>
const token={token_json};
const button=document.getElementById('reset'),status=document.getElementById('status');
button.addEventListener('click',async()=>{{
 if(!confirm('Сбросить логин и пароль администратора?')) return;
 button.disabled=true; status.textContent='Выполняется сброс…';
 try{{
  const r=await fetch('/admin-reset/confirm',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{token}})}});
  if(!r.ok) throw new Error('Код '+r.status);
  localStorage.removeItem('giik.admin.account.v1');
  sessionStorage.removeItem('giik.admin.session.v1');
  status.textContent='Готово. Открываю создание нового администратора…';
  setTimeout(()=>location.replace('/admin-login?reset=1'),350);
 }}catch(e){{status.textContent='Не удалось выполнить сброс. Снова запустите RESET_ADMIN.cmd.';button.disabled=false;}}
}});
</script></body></html>'''

# Capture once: changing files must not make an old process claim to run new code.
UI_REVISION = release_id()

from application import dispatch, student_portal_view, briefing_meta, briefing_banner, BANNER_FILES


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        # Windows otherwise permits two local copies to share the same port.
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(engine, port=8878, *, host='127.0.0.1', api_token=None, allowed_origins=(), api_only=False, legacy_api=True, shared_server=False, public_origin=None):
    lock = threading.Lock()
    token = secrets.token_urlsafe(32)
    if api_token is not None and (not isinstance(api_token, str) or len(api_token) < 24 or not api_token.isascii() or any(c.isspace() for c in api_token)):
        raise ValueError('TRAINING_API_TOKEN: используйте отдельный случайный токен не короче 24 символов без пробелов.')
    if api_only and not api_token:
        raise ValueError('Для отдельного REST-сервера задайте TRAINING_API_TOKEN; это не ключ провайдера ИИ.')
    permitted_origins = set()
    for origin in allowed_origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.path not in ('','/') or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('Разрешённый Origin: точный http(s)://host:port без пути и параметров.')
        permitted_origins.add(origin.rstrip('/'))
    if public_origin:
        parsed_public = urlsplit(public_origin)
        if (not shared_server or parsed_public.scheme != 'https' or not parsed_public.hostname
                or parsed_public.path not in ('','/') or parsed_public.query or parsed_public.fragment
                or parsed_public.username or parsed_public.password):
            raise ValueError('PUBLIC_ORIGIN: нужен точный HTTPS-адрес общего сервера без пути.')
        public_origin = public_origin.rstrip('/')
        permitted_origins.add(public_origin)
    public_host = urlsplit(public_origin).netloc if public_origin else None
    router = RestAPI(engine, lock)
    accounts = Accounts(engine.directory, getattr(engine, 'store', None)) if shared_server else None
    if accounts and not accounts.count():
        raise ValueError('Создайте первую учётную запись: py -3 manage_users.py create admin "Администратор" admin')
    session_cookie_name = 'trainer112_session'
    session_ttl = 12 * 60 * 60
    secure_cookie = bool(public_origin and urlsplit(public_origin).scheme == 'https')

    class Handler(BaseHTTPRequestHandler):
        def session_token(self):
            try:
                cookie = SimpleCookie(); cookie.load(self.headers.get('Cookie', ''))
                morsel = cookie.get(session_cookie_name)
                return morsel.value if morsel else ''
            except Exception:
                return ''

        def account(self, required=True):
            if accounts is None:
                return None
            user = None
            authorization = self.headers.get('Authorization', '')
            if authorization.startswith('Basic '):
                user = accounts.authenticate(authorization)
            if user is None:
                token_value = self.session_token()
                if token_value:
                    user = accounts.authenticate_session(token_value)
            if user is None and required:
                raise APIError(401, 'login_required', 'Введите логин и пароль учётной записи.')
            return user

        def session_cookie(self, token_value):
            parts = [f'{session_cookie_name}={token_value}', 'Path=/', 'HttpOnly', 'SameSite=Lax', f'Max-Age={session_ttl}']
            if secure_cookie:
                parts.append('Secure')
            return '; '.join(parts)

        def clear_session_cookie(self):
            parts = [f'{session_cookie_name}=', 'Path=/', 'HttpOnly', 'SameSite=Lax', 'Max-Age=0']
            if secure_cookie:
                parts.append('Secure')
            return '; '.join(parts)

        @staticmethod
        def role_home(user):
            return '/admin' if user['role'] == 'admin' else '/teacher' if user['role'] == 'teacher' else '/student'

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, *args):
            # Keep request bodies, query strings, student names and UI tokens out of logs.
            return

        def respond(self, code, body, mime='application/json; charset=utf-8', headers=None):
            if getattr(self, '_log_action', None):
                print(f'[WEB] {self.command} {self._log_action}: HTTP {code} request={getattr(self, "_request_id", "-")}', flush=True)
            content = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            origin = self.headers.get('Origin')
            if origin in permitted_origins:
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Access-Control-Expose-Headers', 'Location, X-Request-ID')
                self.send_header('Vary', 'Origin')
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            try:
                if self.command != 'HEAD':
                    self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                # Client cancellation must not undo an operation already saved.
                pass

        def read_json(self, limit=256000):
            if self.headers.get('Transfer-Encoding'):
                raise APIError(400, 'unsupported_transfer', 'Используйте Content-Length без Transfer-Encoding.')
            sizes = self.headers.get_all('Content-Length', [])
            if len(sizes) > 1:
                raise APIError(400, 'invalid_length', 'Повторный Content-Length недопустим.')
            try:
                size = int(sizes[0]) if sizes else 0
            except ValueError:
                raise APIError(400, 'invalid_length', 'Некорректная длина запроса.') from None
            if size < 0:
                raise APIError(400, 'invalid_length', 'Некорректная длина запроса.')
            if size > limit:
                raise APIError(413, 'payload_too_large', f'Запрос превышает {limit} байт.')
            if self.command in ('GET','HEAD'):
                if size:
                    raise APIError(400, 'unexpected_body', 'GET/HEAD не принимают тело запроса.')
                return None
            if not size:
                return {}
            if self.headers.get_content_type() != 'application/json':
                raise APIError(415, 'unsupported_media_type', 'Используйте Content-Type: application/json.')
            try:
                data = json.loads(self.rfile.read(size).decode('utf-8-sig'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError()))
            except (ValueError, UnicodeError, RecursionError):
                raise APIError(400, 'invalid_json', 'Некорректный JSON в теле запроса.') from None
            if not isinstance(data, dict):
                raise APIError(400, 'invalid_json', 'Тело запроса должно быть JSON-объектом.')
            return data

        def rest_request(self):
            request_id = uuid.uuid4().hex
            self._request_id = request_id
            self._log_action = 'REST API'
            headers = {'X-Request-ID': request_id}
            try:
                if not self.local_host():
                    raise APIError(403, 'invalid_host', 'Доступ только через 127.0.0.1.')
                origin = self.headers.get('Origin')
                own_origin = public_origin if public_host and self.headers.get('Host') == public_host else f'http://{self.headers.get("Host")}'
                if origin is not None and origin not in {own_origin, *permitted_origins}:
                    raise APIError(403, 'origin_denied', 'Этот Origin не разрешён для API.')
                path = urlsplit(self.path).path
                if path in (PREFIX + '/health', PREFIX + '/openapi.json'):
                    self._log_action = None
                    if self.command not in ('GET','HEAD'):
                        raise APIError(405, 'method_not_allowed', 'Используйте GET.', headers={'Allow':'GET, HEAD'})
                    self.read_json()
                    if path.endswith('openapi.json'):
                        body = openapi()
                    else:
                        storage = {'backend':'files'}
                        if getattr(engine, 'store', None) is not None:
                            try:
                                storage = engine.store.health()
                            except Exception as exc:
                                raise APIError(503, 'database_unavailable', 'PostgreSQL недоступен: ' + str(exc)) from None
                        body = {'data':{'status':'ok','api_version':'1.0.0','storage':storage},'request_id':request_id}
                    self.respond(200, body, headers=headers); return
                if shared_server and path in (PREFIX + '/auth/login', PREFIX + '/auth/logout', PREFIX + '/auth/me'):
                    self._log_action = 'auth'
                    if self.command == 'OPTIONS':
                        headers.update({'Allow':'GET, POST, OPTIONS','Access-Control-Allow-Methods':'GET, POST, OPTIONS',
                                        'Access-Control-Allow-Headers':'Authorization, Content-Type, X-UI-Token','Access-Control-Max-Age':'600'})
                        self.respond(204, b'', headers=headers); return
                    if path.endswith('/login'):
                        if self.command != 'POST':
                            raise APIError(405, 'method_not_allowed', 'Используйте POST.', headers={'Allow':'POST, OPTIONS'})
                        data = self.read_json(limit=16_000)
                        login = data.get('login'); password = data.get('password'); expected_role = data.get('role')
                        if expected_role not in (None, 'admin', 'teacher', 'student'):
                            raise APIError(422, 'invalid_role', 'Неизвестная роль входа.')
                        user = accounts.authenticate_credentials(login, password)
                        if user is None:
                            raise APIError(401, 'invalid_credentials', 'Неверный логин или пароль.')
                        if expected_role and user['role'] != expected_role:
                            role_names={'admin':'Администратор','teacher':'Преподаватель','student':'Обучающийся'}
                            raise APIError(403, 'wrong_role', f'Эта учётная запись имеет роль «{role_names.get(user["role"], user["role"])}».')
                        session_value = accounts.create_session(user['id'], ttl_seconds=session_ttl)
                        headers['Set-Cookie'] = self.session_cookie(session_value)
                        self.respond(200, {'data':{'user':user,'home':self.role_home(user)},'request_id':request_id}, headers=headers); return
                    if path.endswith('/logout'):
                        if self.command != 'POST':
                            raise APIError(405, 'method_not_allowed', 'Используйте POST.', headers={'Allow':'POST, OPTIONS'})
                        self.read_json(limit=1024)
                        session_value = self.session_token()
                        if session_value:
                            accounts.revoke_session(session_value)
                        headers['Set-Cookie'] = self.clear_session_cookie()
                        self.respond(200, {'data':{'logged_out':True},'request_id':request_id}, headers=headers); return
                    if self.command != 'GET':
                        raise APIError(405, 'method_not_allowed', 'Используйте GET.', headers={'Allow':'GET, OPTIONS'})
                    self.read_json()
                    user = self.account()
                    self.respond(200, {'data':user,'request_id':request_id}, headers=headers); return

                if shared_server and path == PREFIX + '/settings':
                    self._log_action = 'settings'
                    if self.command == 'OPTIONS':
                        headers.update({'Allow':'GET, PUT, OPTIONS','Access-Control-Allow-Methods':'GET, PUT, OPTIONS',
                                        'Access-Control-Allow-Headers':'Authorization, Content-Type, X-UI-Token','Access-Control-Max-Age':'600'})
                        self.respond(204, b'', headers=headers); return
                    user = self.account()
                    if user['role'] != 'admin':
                        raise APIError(403, 'forbidden', 'Настройки системы доступны только администратору.')
                    if getattr(engine, 'store', None) is None:
                        raise APIError(503, 'database_required', 'Общие настройки требуют PostgreSQL.')
                    if self.command == 'GET':
                        self.read_json()
                        value = engine.store.load_setting('admin_ui') or {}
                        self.respond(200, {'data':value,'request_id':request_id}, headers=headers); return
                    if self.command == 'PUT':
                        data = self.read_json(limit=64_000)
                        allowed = {'system_name','timezone'}
                        if set(data) - allowed:
                            raise APIError(422, 'invalid_settings', 'Можно менять только название системы и часовой пояс.')
                        name = data.get('system_name','ИИ-тренажёр 112')
                        timezone_name = data.get('timezone','')
                        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 120 or not isinstance(timezone_name,str) or len(timezone_name) > 80:
                            raise APIError(422, 'invalid_settings', 'Некорректные настройки.')
                        value = {'system_name':name.strip(),'timezone':timezone_name}
                        engine.store.save_setting('admin_ui', value)
                        self.respond(200, {'data':value,'request_id':request_id}, headers=headers); return
                    raise APIError(405, 'method_not_allowed', 'Используйте GET или PUT.', headers={'Allow':'GET, PUT, OPTIONS'})

                if shared_server and path == PREFIX + '/workshop':
                    self._log_action = 'workshop'
                    if self.command == 'OPTIONS':
                        headers.update({'Allow':'GET, PUT, OPTIONS','Access-Control-Allow-Methods':'GET, PUT, OPTIONS',
                                        'Access-Control-Allow-Headers':'Authorization, Content-Type, X-UI-Token','Access-Control-Max-Age':'600'})
                        self.respond(204, b'', headers=headers); return
                    user = self.account()
                    if user['role'] not in ('teacher','admin'):
                        raise APIError(403, 'forbidden', 'Мастерская карточек доступна преподавателю или администратору.')
                    if getattr(engine, 'store', None) is None:
                        raise APIError(503, 'database_required', 'Общая мастерская требует PostgreSQL.')
                    if self.command == 'GET':
                        self.read_json()
                        state = engine.store.load_workshop_state(user['id'])
                        self.respond(200, {'data':{'state':state},'request_id':request_id}, headers=headers); return
                    if self.command == 'PUT':
                        data = self.read_json(limit=8_000_000)
                        state = data.get('state')
                        if not isinstance(state, dict) or state.get('version') != 1 or not isinstance(state.get('cards'), list) or len(state['cards']) > 500:
                            raise APIError(422, 'invalid_workshop', 'Неверная структура мастерской карточек.')
                        # Bound the few top-level values that could otherwise grow without limit.
                        if not isinstance(state.get('teacher',''), str) or len(state.get('teacher','')) > 160:
                            raise APIError(422, 'invalid_workshop', 'Некорректное имя преподавателя.')
                        engine.store.save_workshop_state(user['id'], state)
                        self.respond(200, {'data':{'saved':True},'request_id':request_id}, headers=headers); return
                    raise APIError(405, 'method_not_allowed', 'Используйте GET или PUT.', headers={'Allow':'GET, PUT, OPTIONS'})

                if shared_server and path == PREFIX + '/accounts/register':
                    self._log_action = 'accounts/register'
                    if self.command == 'OPTIONS':
                        headers.update({'Allow':'POST, OPTIONS','Access-Control-Allow-Methods':'POST, OPTIONS',
                                        'Access-Control-Allow-Headers':'Authorization, Content-Type, X-UI-Token','Access-Control-Max-Age':'600'})
                        self.respond(204, b'', headers=headers); return
                    if self.command != 'POST':
                        raise APIError(405, 'method_not_allowed', 'Используйте POST.', headers={'Allow':'POST, OPTIONS'})
                    if os.environ.get('ALLOW_SELF_REGISTRATION','').strip().lower() not in ('1','true','yes','on'):
                        raise APIError(403, 'registration_disabled', 'Самостоятельная регистрация отключена администратором.')
                    data = self.read_json()
                    try:
                        created = accounts.create(data['login'], data['full_name'], 'student', data['password'])
                    except KeyError:
                        raise APIError(422, 'missing_fields', 'Нужны login, full_name, password.') from None
                    except (ValueError, AttributeError, TypeError) as exc:
                        raise APIError(422, 'invalid_field', str(exc)) from None
                    self.respond(201, {'data':created,'request_id':request_id}, headers=headers); return

                account_match = re.fullmatch(re.escape(PREFIX) + r'/accounts/(\d+)(/password)?', path) if shared_server else None
                if shared_server and (path in (PREFIX + '/accounts', PREFIX + '/accounts/me') or account_match):
                    self._log_action = 'accounts'
                    if self.command == 'OPTIONS':
                        allow = 'GET, POST, PATCH, OPTIONS'
                        headers.update({'Allow':allow,'Access-Control-Allow-Methods':allow,
                                        'Access-Control-Allow-Headers':'Authorization, Content-Type, X-UI-Token','Access-Control-Max-Age':'600'})
                        self.respond(204, b'', headers=headers); return
                    user = self.account()
                    if path.endswith('/me') and self.command == 'GET':
                        self.read_json()
                        self.respond(200, {'data':user,'request_id':request_id}, headers=headers); return
                    if user['role'] != 'admin':
                        raise APIError(403, 'forbidden', 'Действие доступно только администратору.')
                    if path == PREFIX + '/accounts':
                        if self.command == 'GET':
                            self.read_json()
                            self.respond(200, {'data':accounts.list_users(),'request_id':request_id}, headers=headers); return
                        if self.command == 'POST':
                            data = self.read_json()
                            try:
                                created = accounts.create(data['login'], data['full_name'], data['role'], data['password'])
                            except KeyError:
                                raise APIError(422, 'missing_fields', 'Нужны login, full_name, role, password.') from None
                            except (ValueError, AttributeError, TypeError) as exc:
                                raise APIError(422, 'invalid_field', str(exc)) from None
                            self.respond(201, {'data':created,'request_id':request_id}, headers=headers); return
                    if account_match:
                        user_id = int(account_match.group(1)); password_path = bool(account_match.group(2))
                        data = self.read_json()
                        try:
                            if password_path and self.command == 'POST':
                                accounts.set_password(user_id, data['password'])
                                self.respond(200, {'data':{'updated':True},'request_id':request_id}, headers=headers); return
                            if not password_path and self.command == 'PATCH':
                                allowed = {'role','active','full_name'}
                                if not data or set(data) - allowed:
                                    raise ValueError('Можно менять только role, active и full_name.')
                                updated = accounts.update(user_id, role=data.get('role'), active=data.get('active'), full_name=data.get('full_name'))
                                self.respond(200, {'data':updated,'request_id':request_id}, headers=headers); return
                        except KeyError:
                            raise APIError(422, 'missing_fields', 'Укажите password.') from None
                        except (ValueError, AttributeError, TypeError) as exc:
                            raise APIError(422, 'invalid_field', str(exc)) from None
                    raise APIError(405, 'method_not_allowed', 'HTTP-метод не поддерживается для управления пользователями.')
                if self.command == 'OPTIONS':
                    methods = router.allowed_methods(self.path)
                    requested_method = self.headers.get('Access-Control-Request-Method')
                    requested_headers = {h.strip().lower() for h in self.headers.get('Access-Control-Request-Headers','').split(',') if h.strip()}
                    if requested_method and requested_method not in methods or requested_headers - {'authorization','content-type','x-ui-token'}:
                        raise APIError(403, 'preflight_denied', 'Метод или заголовки не разрешены для этого API.')
                    headers.update({'Allow':', '.join(methods), 'Access-Control-Allow-Methods':', '.join(methods),
                                    'Access-Control-Allow-Headers':'Authorization, Content-Type, X-UI-Token', 'Access-Control-Max-Age':'600'})
                    self.respond(204, b'', headers=headers); return
                user = self.account()
                supplied_ui = self.headers.get('X-UI-Token', '')
                supplied_auth = self.headers.get('Authorization', '')
                ui_ok = not api_only and secrets.compare_digest(supplied_ui.encode(), token.encode())
                bearer_ok = api_token and secrets.compare_digest(supplied_auth.encode(), ('Bearer ' + api_token).encode())
                if not (ui_ok or bearer_ok or user):
                    raise APIError(401, 'unauthorized', 'Нужен токен локального интерфейса или отдельный токен REST API.', headers={'WWW-Authenticate':'Bearer'})
                try:
                    route, _ = router.resolve('GET' if self.command == 'HEAD' else self.command, self.path)
                    self._log_action = route.action + (('/' + route.operation) if route.operation else '')
                except APIError:
                    pass
                body = self.read_json()
                if user is not None:
                    route, path_values = router.resolve('GET' if self.command == 'HEAD' else self.command, self.path)
                    payload = router.payload(route, path_values, self.path, body)
                    try:
                        check_action(user, route.action, payload)
                    except PermissionError as exc:
                        raise APIError(403, 'forbidden', str(exc)) from None
                    if user['role'] == 'student' and route.action in {'student','ask','hint','save_card','submit','connect','channel','assess'}:
                        try:
                            session = engine.load(payload['id'])
                        except (ValueError, FileNotFoundError):
                            raise APIError(404, 'not_found', 'Работа не найдена.') from None
                        if session.get('student') != user['full_name']:
                            raise APIError(403, 'forbidden', 'Работа другого обучающегося недоступна.')
                    if user['role'] == 'teacher' and route.action.startswith('training_') and 'resource_id' in payload:
                        import curriculum
                        try:
                            training = curriculum.get(engine, payload['resource_id'])
                        except (ValueError, FileNotFoundError):
                            raise APIError(404, 'not_found', 'Тренировка не найдена.') from None
                        if training.get('teacher') != user['full_name']:
                            raise APIError(403, 'forbidden', 'Это занятие другого преподавателя.')
                    if user['role'] == 'student' and route.action == 'training_lobby':
                        import curriculum
                        try:
                            training = curriculum.get(engine, payload['resource_id'])
                        except (ValueError, FileNotFoundError):
                            raise APIError(404, 'not_found', 'Комната не найдена.') from None
                        if not any(row['student'] == user['full_name'] for row in training['participants']):
                            raise APIError(403, 'forbidden', 'Вы не входите в эту комнату.')
                result = router.handle('GET' if self.command == 'HEAD' else self.command, self.path, body)
                headers.update(result.headers)
                self.respond(result.status, {'data': result.data, 'request_id':request_id}, headers=headers)
            except APIError as exc:
                headers.update(exc.headers)
                self.respond(exc.status, exc.body(request_id), headers=headers)
            except Exception:
                exc = APIError(500, 'internal_error', 'Не удалось выполнить запрос. Сохранённые работы доступны после обновления страницы.')
                self.respond(exc.status, exc.body(request_id), headers=headers)

        def local_host(self):
            supplied=self.headers.get('Host','')
            if public_host and supplied == public_host:
                return True
            if not self.server.classroom:
                return supplied == f'127.0.0.1:{self.server.server_port}'
            try:
                address, port = supplied.rsplit(':',1)
                ip = ipaddress.ip_address(address)
                return int(port) == self.server.server_port and ip.is_private and address == self.connection.getsockname()[0]
            except (ValueError, TypeError):
                return False

        def do_GET(self):
            if urlsplit(self.path).path.startswith('/api/') and urlsplit(self.path).path != '/api/docs':
                self.rest_request(); return
            if api_only:
                self.respond(404, {'error': 'Используйте /api/v1/health или /api/v1/openapi.json.'}); return
            if not self.local_host():
                self.respond(403, {'error': 'Доступ только через 127.0.0.1.'}); return
            parsed_request = urlsplit(self.path)
            path = parsed_request.path
            if shared_server and path == '/admin-reset':
                self.respond(404, {'error':'Локальный сброс недоступен на общем сервере.'}); return
            page_user = None
            if shared_server:
                page_user = self.account(required=False)
                if path == '/admin-login':
                    self.send_response(302); self.send_header('Location','/login?role=admin'); self.send_header('Cache-Control','no-store'); self.end_headers(); return
                if path in ('/', '/login') and page_user:
                    self.send_response(302); self.send_header('Location', self.role_home(page_user)); self.send_header('Cache-Control','no-store'); self.end_headers(); return
                protected_roles = {
                    '/admin': {'admin'},
                    '/teacher': {'teacher','admin'}, '/cards': {'teacher','admin'}, '/scenarios': {'teacher','admin'},
                    '/student': {'student','admin'},
                    '/training': {'admin','teacher','student'},
                }
                if path in protected_roles:
                    if page_user is None:
                        hint = 'admin' if path == '/admin' else 'teacher' if path in ('/teacher','/cards','/scenarios') else 'student' if path == '/student' else ''
                        target = '/login?' + (('role=' + hint + '&') if hint else '') + 'next=' + quote(path)
                        self.send_response(302); self.send_header('Location', target); self.send_header('Cache-Control','no-store'); self.end_headers(); return
                    if page_user['role'] not in protected_roles[path]:
                        self.respond(403, {'error':{'code':'forbidden','message':'Эта страница не доступна вашей системной роли.'}}); return
            if path == '/admin-reset':
                params = parse_qs(parsed_request.query, keep_blank_values=True)
                candidate = (params.get('token') or [''])[0]
                if not _valid_admin_reset_token(candidate):
                    self.respond(403, 'Ссылка сброса недействительна или истекла.'.encode('utf-8'), 'text/plain; charset=utf-8'); return
                self.respond(200, _admin_reset_page(candidate).encode('utf-8'), 'text/html; charset=utf-8'); return
            if path == '/health':
                status = {'app':'ai-project-ui', 'revision':UI_REVISION,
                          'pages':['/', '/login', '/teacher', '/student', '/admin-login', '/admin', '/cards', '/training', '/scenarios']}
                if not shared_server:
                    status.update(root=str(ROOT), pid=os.getpid())
                self.respond(200, status); return
            if path.startswith('/banners/'):
                filename = path.removeprefix('/banners/')
                if filename not in BANNER_FILES.values():
                    self.respond(404, {'error': 'Не найдено'}); return
                file_path = ROOT / 'ui' / 'banners' / filename
                if not file_path.is_file():
                    self.respond(404, {'error': 'Не найдено'}); return
                self.respond(200, file_path.read_bytes(), 'image/webp'); return
<<<<<<< HEAD
            if path in ('/login/', '/student/', '/teacher/', '/admin-login/', '/admin/', '/cards/', '/training/', '/scenarios/'):
=======
            if path in ('/student/', '/teacher/', '/admin-login/', '/admin/', '/cards/', '/training/', '/scenarios/'):
>>>>>>> ec5491b6745f1dd11607901b6ecc81befa475fae
                self.send_response(302)
                self.send_header('Location', path.rstrip('/'))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                return
            # Keep the original welcome artwork at / in every mode.
            # /welcome-login.js adds server login/password fields without replacing the design.
            names = {'/api/docs': ('api-docs.html', 'text/html'), '/api-client.js': ('api-client.js', 'text/javascript'),
                     '/api-routes.js': ('api-routes.js', 'text/javascript'), '/admin-role-manager.js': ('admin-role-manager.js', 'text/javascript'), '/dispatcher-ai-examples.js': ('dispatcher-ai-examples.js', 'text/javascript'), '/': ('react.html', 'text/html'), '/login': ('login.html', 'text/html'), '/teacher': ('react.html', 'text/html'),
                     '/admin-login': ('react.html', 'text/html'), '/admin': ('react.html', 'text/html'), '/admin.css': ('admin.css', 'text/css'),
                     '/student': ('react.html', 'text/html'), '/student.css': ('student.css', 'text/css'), '/lobby.css': ('lobby.css', 'text/css'), '/classroom.css': ('classroom.css', 'text/css'),
                     '/theme.css': ('theme.css', 'text/css'),
                     '/address.css': ('address.css', 'text/css'),
                     '/geo/addresses.json': ('geo/addresses.json', 'application/json'),
                     '/geo/map.json': ('geo/map.json', 'application/json'),
                     '/workspace.css': ('workspace.css', 'text/css'),
                     '/scenarios': ('scenarios.html', 'text/html'),
                     '/scenarios.css': ('scenarios.css', 'text/css'),
                     '/scenarios.js': ('scenarios.js', 'text/javascript'),
                     '/enhancements.js': ('enhancements.js', 'text/javascript'), '/shared-auth-ui.js': ('shared-auth-ui.js', 'text/javascript'),
                     '/react/app.js': ('react/app.js', 'text/javascript'),
                     '/welcome.css': ('welcome.css', 'text/css'), '/welcome-login.js': ('welcome-login.js', 'text/javascript'),
                     '/hero-background.svg': ('hero-background.svg', 'image/svg+xml'),
                     '/hero-logo.svg': ('hero-logo.svg', 'image/svg+xml'),
                     '/cards': ('react.html', 'text/html'),
                     '/teacher.css': ('teacher.css', 'text/css'), '/teacher.js': ('teacher.js', 'text/javascript'),
                     '/teacher-shell.js': ('teacher-shell.js', 'text/javascript'),
                     '/training': ('index.html', 'text/html'), '/cards.js': ('cards.js', 'text/javascript'),
                     '/making.css': ('making.css', 'text/css'), '/cards.css': ('cards.css', 'text/css'), '/app.js': ('app.js', 'text/javascript'),
                     '/app.css': ('app.css', 'text/css'), '/workflows.js': ('workflows.js', 'text/javascript')}
            if path not in names:
                self.respond(404, {'error': 'Не найдено'}); return
            name, mime = names[path]
            body = (ROOT / 'ui' / name).read_text(encoding='utf-8').replace('__TOKEN__', token)
            if name == 'react.html':
                styles = ['/welcome.css'] if path == '/' else (['/admin.css'] if path in ('/login','/admin','/admin-login') else (['/making.css', '/student.css'] if path == '/student' else (['/cards.css', '/teacher.css', '/making.css'] if path == '/cards' else ['/teacher.css'])))
                body = body.replace('__STYLES__', ''.join(f'<link rel="stylesheet" href="{href}">' for href in ['/theme.css', '/address.css', *styles, *(['/workspace.css'] if path == '/teacher' else []), *(['/lobby.css'] if path in ('/teacher', '/student') else []), *(['/classroom.css'] if path == '/teacher' else [])]))
                body = body.replace('__BODY_CLASS__', '' if path == '/' else ('admin-app' if path in ('/login','/admin','/admin-login') else ('student-app' if path == '/student' else ('teacher-app cards-page' if path == '/cards' else 'teacher-app'))))
                if shared_server:
                    identity = json.dumps({'name':page_user['full_name'],'login':page_user['login'],'role':page_user['role']}, ensure_ascii=False) if page_user else 'null'
                    bootstrap = f'''<script>(function(){{const u={identity};globalThis.TRAINER_SHARED_SERVER=true;globalThis.TRAINER_USER=u;
if(!u)return;
if(u.role==='admin'){{localStorage.setItem('giik.admin.account.v1',JSON.stringify({{version:2,name:u.name,login:u.login,password_hash:'server-managed',server_managed:true}}));sessionStorage.setItem('giik.admin.session.v1',JSON.stringify({{ok:true,login:u.login,server_managed:true}}));}}
if(u.role==='teacher'||u.role==='admin')localStorage.setItem('giik.teacher.profile.v1',JSON.stringify({{name:u.name,server_managed:true}}));
if(u.role==='student'||u.role==='admin'){{localStorage.setItem('giik.student.profile.v1',JSON.stringify({{name:u.name,server_managed:true}}));localStorage.setItem('practice:student',u.name);sessionStorage.setItem('practice:student:tab',u.name);}}
}})();</script>'''
                    body = body.replace('</head>', bootstrap + '</head>')
                    body = body.replace('</body>', '<script defer src="/shared-auth-ui.js"></script></body>')
            self.respond(200, body.encode(), mime + '; charset=utf-8')

        def do_POST(self):
            path = urlsplit(self.path).path
            if path == '/admin-reset/confirm':
                if shared_server:
                    self.respond(404, {'error':'В режиме общего сервера локальный сброс администратора отключён.'}); return
                origin = f'http://{self.headers.get("Host","")}'
                if not self.local_host() or self.headers.get('Origin') not in (None, origin):
                    self.respond(403, {'error':'Недопустимый источник запроса.'}); return
                try:
                    data = self.read_json()
                    candidate = data.get('token', '')
                    if not _valid_admin_reset_token(candidate, consume=True):
                        self.respond(403, {'error':'Ссылка сброса недействительна или истекла.'}); return
                    self.respond(200, {'ok':True}); return
                except APIError as exc:
                    self.respond(exc.status, {'error':exc.message if hasattr(exc,'message') else 'Некорректный запрос.'}); return
            if path.startswith('/api/'):
                self.rest_request(); return
            if shared_server:
                self.respond(410, {'error':'Используйте REST API /api/v1.'}); return
            if not legacy_api or api_only:
                self.respond(410, {'error': 'Старый RPC отключён. Используйте REST API /api/v1.'}); return
            origin = f'http://{self.headers.get("Host","")}'
            if not self.local_host() or self.headers.get('Origin') not in (None, origin) or self.headers.get('X-UI-Token') != token:
                self.respond(403, {'error': 'Откройте интерфейс заново.'}); return
            if self.path != '/api':
                self.respond(404, {'error': 'Не найдено'}); return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 256000:
                    raise ValueError('Слишком большой запрос.')
                data = json.loads(self.rfile.read(size))
                with lock:
                    result = dispatch(engine, data['action'], data.get('payload', {}))
                self.respond(200, {'result': result}, headers={'X-Deprecated-API':'Use /api/v1'})
            except (ValueError, KeyError, TypeError, FileNotFoundError) as exc:
                self.respond(400, {'error': str(exc) if isinstance(exc, ValueError) else 'Данные не найдены или имеют неверный формат.'})
            except RuntimeError as exc:
                self.respond(502, {'error': str(exc)})
            except Exception:
                self.respond(500, {'error': 'Не удалось выполнить действие. Сохранённые работы доступны после обновления страницы.'})

        do_PUT = rest_request
        do_PATCH = rest_request
        do_DELETE = rest_request
        do_OPTIONS = rest_request
        do_HEAD = rest_request

    if host not in ('127.0.0.1','0.0.0.0'):
        raise ValueError('Сервер можно открыть локально или в учебной сети.')
    server = LocalServer((host, port), Handler)
    server.classroom = host == '0.0.0.0'
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8878)
    parser.add_argument('--host', choices=('127.0.0.1','0.0.0.0'), default='127.0.0.1')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--data-dir')
    parser.add_argument('--api-only', action='store_true', help='Только REST API, без интерфейса')
    parser.add_argument('--allowed-origin', action='append', default=[], help='Точный Origin отдельного frontend')
    parser.add_argument('--no-legacy-api', action='store_true', help='Отключить прежний POST /api')
    parser.add_argument('--shared-server', action='store_true', help='Общие учётные записи и проверка ролей для нескольких компьютеров')
    parser.add_argument('--database-url', help='PostgreSQL DSN; по умолчанию DATABASE_URL')
    parser.add_argument('--auto-migrate', action='store_true', help='Применить безопасные миграции схемы PostgreSQL при запуске')
    parser.add_argument('--require-postgres', action='store_true', help='Не запускать общий сервер без PostgreSQL')
    parser.add_argument('--public-origin', help='HTTPS-адрес для доступа через обратный прокси, например https://trainer.example.org')
    args = parser.parse_args()
    if not args.api_only:
        validate_ui()
    database_url = args.database_url if args.database_url is not None else os.environ.get('DATABASE_URL')
    if args.require_postgres and not database_url:
        raise RuntimeError('Для серверного режима задайте DATABASE_URL на PostgreSQL.')
    store = store_from_url(database_url, auto_migrate=args.auto_migrate) if database_url else None
    engine = Engine(AIProvider(), args.data_dir, store=store)
    try:
        server = make_server(engine, args.port, host=args.host, api_token=os.environ.get('TRAINING_API_TOKEN'),
                             allowed_origins=args.allowed_origin, api_only=args.api_only,
                             legacy_api=not args.no_legacy_api, shared_server=args.shared_server,
                             public_origin=args.public_origin)
    except OSError:
        if not args.no_browser and not args.data_dir and not args.api_only:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/health', timeout=2) as r:
                    status = json.load(r)
                if compatible_server(status, ROOT, UI_REVISION):
                    webbrowser.open(f'http://127.0.0.1:{args.port}'); return
            except Exception:
                pass
        raise RuntimeError(
            f'Порт {args.port} уже занят. Возможно, после обновления остался старый сервер.\n'
            'Закончите текущую работу и запустите RESTART.cmd из этой же папки.\n'
            'Если программа запущена из другой папки, сначала закройте ту копию.\n'
            f'Текущая папка: {ROOT}\nДиагностика: http://127.0.0.1:{args.port}/health') from None
    url = f'http://127.0.0.1:{server.server_port}'
    if args.api_only or args.no_browser:
        print('REST API: ' + url + '/api/v1', flush=True)
    if not args.no_browser and not args.api_only:
        threading.Timer(.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        (ROOT / 'ui-error.log').write_text(str(exc), encoding='utf-8')
        if os.name == 'nt':
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, str(exc), '112 — не удалось запустить интерфейс', 0x10)
            except Exception:
                pass
        raise
