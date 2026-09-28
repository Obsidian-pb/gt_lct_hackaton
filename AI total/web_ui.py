"""Local single-user browser client for the independent training engine."""
import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import socket
import threading
import urllib.request
from urllib.parse import urlsplit
import webbrowser
from datetime import datetime

from ai_core import Engine
from provider import AIProvider
from ui_release import release_id, validate_ui, compatible_server
from api_contract import PREFIX, openapi
from rest_api import APIError, RestAPI
import uuid

ROOT = Path(__file__).resolve().parent
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


def make_server(engine, port=8878, *, api_token=None, allowed_origins=(), api_only=False, legacy_api=True):
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
    router = RestAPI(engine, lock)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, *args):
            pass

        def respond(self, code, body, mime='application/json; charset=utf-8', headers=None):
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

        def read_json(self):
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
            if size > 256000:
                raise APIError(413, 'payload_too_large', 'Запрос превышает 256000 байт.')
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
            headers = {'X-Request-ID': request_id}
            try:
                if not self.local_host():
                    raise APIError(403, 'invalid_host', 'Доступ только через 127.0.0.1.')
                origin = self.headers.get('Origin')
                own_origin = f'http://127.0.0.1:{self.server.server_port}'
                if origin is not None and origin not in {own_origin, *permitted_origins}:
                    raise APIError(403, 'origin_denied', 'Этот Origin не разрешён для API.')
                path = urlsplit(self.path).path
                if path in (PREFIX + '/health', PREFIX + '/openapi.json'):
                    if self.command not in ('GET','HEAD'):
                        raise APIError(405, 'method_not_allowed', 'Используйте GET.', headers={'Allow':'GET, HEAD'})
                    self.read_json()
                    body = openapi() if path.endswith('openapi.json') else {'data':{'status':'ok','api_version':'1.0.0'},'request_id':request_id}
                    self.respond(200, body, headers=headers); return
                if self.command == 'OPTIONS':
                    methods = router.allowed_methods(self.path)
                    requested_method = self.headers.get('Access-Control-Request-Method')
                    requested_headers = {h.strip().lower() for h in self.headers.get('Access-Control-Request-Headers','').split(',') if h.strip()}
                    if requested_method and requested_method not in methods or requested_headers - {'authorization','content-type','x-ui-token'}:
                        raise APIError(403, 'preflight_denied', 'Метод или заголовки не разрешены для этого API.')
                    headers.update({'Allow':', '.join(methods), 'Access-Control-Allow-Methods':', '.join(methods),
                                    'Access-Control-Allow-Headers':'Authorization, Content-Type, X-UI-Token', 'Access-Control-Max-Age':'600'})
                    self.respond(204, b'', headers=headers); return
                supplied_ui = self.headers.get('X-UI-Token', '')
                supplied_auth = self.headers.get('Authorization', '')
                ui_ok = not api_only and secrets.compare_digest(supplied_ui.encode(), token.encode())
                bearer_ok = api_token and secrets.compare_digest(supplied_auth.encode(), ('Bearer ' + api_token).encode())
                # /api/v1/auth/* is protected by its own JWT checks (Этап 2.1),
                # so the legacy UI/API tokens are not required for it.
                auth_path = path.startswith(PREFIX + '/auth/')
                if not auth_path and not (ui_ok or bearer_ok):
                    raise APIError(401, 'unauthorized', 'Нужен токен локального интерфейса или отдельный токен REST API.', headers={'WWW-Authenticate':'Bearer'})
                body = self.read_json()
                result = router.handle('GET' if self.command == 'HEAD' else self.command, self.path, body, authorization=supplied_auth)
                headers.update(result.headers)
                self.respond(result.status, {'data': result.data, 'request_id':request_id}, headers=headers)
            except APIError as exc:
                headers.update(exc.headers)
                self.respond(exc.status, exc.body(request_id), headers=headers)
            except Exception:
                exc = APIError(500, 'internal_error', 'Не удалось выполнить запрос. Сохранённые работы доступны после обновления страницы.')
                self.respond(exc.status, exc.body(request_id), headers=headers)

        def local_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            if urlsplit(self.path).path.startswith('/api/') and urlsplit(self.path).path != '/api/docs':
                self.rest_request(); return
            if api_only:
                self.respond(404, {'error': 'Используйте /api/v1/health или /api/v1/openapi.json.'}); return
            if not self.local_host():
                self.respond(403, {'error': 'Доступ только через 127.0.0.1.'}); return
            path = urlsplit(self.path).path
            if path == '/health':
                self.respond(200, {'app': 'ai-project-ui', 'root': str(ROOT),
                                   'revision': UI_REVISION, 'pid': os.getpid(),
                                   'pages': ['/', '/teacher', '/student', '/admin-login', '/admin', '/cards', '/training', '/scenarios']}); return
            if path.startswith('/banners/'):
                filename = path.removeprefix('/banners/')
                if filename not in BANNER_FILES.values():
                    self.respond(404, {'error': 'Не найдено'}); return
                file_path = ROOT / 'ui' / 'banners' / filename
                if not file_path.is_file():
                    self.respond(404, {'error': 'Не найдено'}); return
                self.respond(200, file_path.read_bytes(), 'image/png'); return
            if path in ('/student/', '/teacher/', '/admin-login/', '/admin/', '/cards/', '/training/', '/scenarios/'):
                self.send_response(302)
                self.send_header('Location', path.rstrip('/'))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                return
            names = {'/api/docs': ('api-docs.html', 'text/html'), '/api-client.js': ('api-client.js', 'text/javascript'),
                     '/api-routes.js': ('api-routes.js', 'text/javascript'), '/': ('react.html', 'text/html'), '/teacher': ('react.html', 'text/html'),
                     '/admin-login': ('react.html', 'text/html'), '/admin': ('react.html', 'text/html'), '/admin.css': ('admin.css', 'text/css'),
                     '/student': ('react.html', 'text/html'), '/student.css': ('student.css', 'text/css'),
                     '/theme.css': ('theme.css', 'text/css'),
                     '/address.css': ('address.css', 'text/css'),
                     '/geo/addresses.json': ('geo/addresses.json', 'application/json'),
                     '/geo/map.json': ('geo/map.json', 'application/json'),
                     '/workspace.css': ('workspace.css', 'text/css'),
                     '/scenarios': ('scenarios.html', 'text/html'),
                     '/scenarios.css': ('scenarios.css', 'text/css'),
                     '/scenarios.js': ('scenarios.js', 'text/javascript'),
                     '/enhancements.js': ('enhancements.js', 'text/javascript'),
                     '/react/app.js': ('react/app.js', 'text/javascript'),
                     '/welcome.css': ('welcome.css', 'text/css'),
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
                styles = ['/welcome.css'] if path == '/' else (['/admin.css'] if path in ('/admin','/admin-login') else (['/making.css', '/student.css'] if path == '/student' else (['/cards.css', '/teacher.css', '/making.css'] if path == '/cards' else ['/teacher.css'])))
                body = body.replace('__STYLES__', ''.join(f'<link rel="stylesheet" href="{href}">' for href in ['/theme.css', '/address.css', *styles, *(['/workspace.css'] if path == '/teacher' else [])]))
                body = body.replace('__BODY_CLASS__', '' if path == '/' else ('admin-app' if path in ('/admin','/admin-login') else ('student-app' if path == '/student' else ('teacher-app cards-page' if path == '/cards' else 'teacher-app'))))
            self.respond(200, body.encode(), mime + '; charset=utf-8')

        def do_POST(self):
            if urlsplit(self.path).path.startswith('/api/'):
                self.rest_request(); return
            if not legacy_api or api_only:
                self.respond(410, {'error': 'Старый RPC отключён. Используйте REST API /api/v1.'}); return
            origin = f'http://127.0.0.1:{self.server.server_port}'
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

    server = LocalServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8878)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--data-dir')
    parser.add_argument('--api-only', action='store_true', help='Только REST API, без интерфейса')
    parser.add_argument('--allowed-origin', action='append', default=[], help='Точный Origin отдельного frontend')
    parser.add_argument('--no-legacy-api', action='store_true', help='Отключить прежний POST /api')
    args = parser.parse_args()
    if not args.api_only:
        validate_ui()
    engine = Engine(AIProvider(), args.data_dir)
    try:
        server = make_server(engine, args.port, api_token=os.environ.get('TRAINING_API_TOKEN'),
                             allowed_origins=args.allowed_origin, api_only=args.api_only, legacy_api=not args.no_legacy_api)
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
