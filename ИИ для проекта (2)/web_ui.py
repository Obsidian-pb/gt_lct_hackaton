"""Local single-user browser client for the independent training engine."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import urllib.request
import webbrowser

from ai_core import Engine, FIELDS, LEVELS, VERDICTS, validate_task
from provider import GigaChat
from dds import WORKFLOWS, ACTION_LABELS

ROOT = Path(__file__).resolve().parent


def dispatch(engine, action, p):
    if action == 'home':
        return {'count': len(engine.approved_tasks()), 'fields': FIELDS, 'levels': LEVELS, 'verdicts': VERDICTS,
                'workflows': WORKFLOWS, 'action_labels': ACTION_LABELS,
                'counts': {key: len(engine.approved_tasks(key)) for key in WORKFLOWS}}
    if action == 'tasks':
        return engine.list_items('t')
    if action == 'create':
        return engine.sample(p['level'], p.get('workflow', 'caller')) if p.get('sample') else engine.draft(p['topic'], p['level'], p.get('workflow', 'caller'))
    if action == 'save_task':
        task = engine.load(p['id'])
        if not task['id'].startswith('t-') or task['status'] != 'draft':
            raise ValueError('Изменять можно только черновик задания.')
        for key in ('title', 'opening', 'persona', 'fields'):
            task[key] = p[key]
        if task.get('workflow') == 'dds':
            for key in ('incoming_card', 'verification_notes', 'service', 'faults', 'actions'):
                task[key] = p[key]
        validate_task(task)
        return engine.save(task)
    if action == 'approve':
        return engine.approve(p['id'], p['teacher'])
    if action == 'start':
        return engine.start_assigned(p['student'], p.get('workflow'))
    if action == 'connect':
        return engine.connect_service(p['id'])
    if action == 'channel':
        return engine.set_channel(p['id'], p['mode'])
    if action == 'sessions':
        return [engine.student_view(s['id']) for s in engine.list_items('s') if s['student'] == p['student']]
    if action == 'student':
        return engine.student_view(p['id'])
    if action == 'ask':
        engine.ask(p['id'], p['question'], p.get('source', 'text'))
        return engine.student_view(p['id'])
    if action == 'hint':
        engine.hint(p['id'])
        return engine.student_view(p['id'])
    if action in ('save_card', 'submit'):
        s = engine._active(p['id'])
        card = p['card']
        if not isinstance(card, dict) or set(card) != set(FIELDS) or any(not isinstance(v, str) or len(v) > 2000 for v in card.values()):
            raise ValueError('Проверьте поля карточки: не более 2000 символов в каждом.')
        # Validate the entire card before changing any fields.
        for key, value in card.items():
            if value != s['card'][key]:
                engine.set_field(p['id'], key, value)
        if action == 'submit':
            engine.submit(p['id'])
        return engine.student_view(p['id'])
    if action == 'assess':
        engine.assess(p['id'])
        return {'status': 'pending_teacher'}
    if action == 'works':
        return [{'id': s['id'], 'title': s['task']['title'], 'student': s['student'], 'status': s['status']} for s in engine.list_items('s') if s['status'] != 'active']
    if action == 'review':
        s = engine.load(p['id'])
        if not s['id'].startswith('s-') or s['status'] == 'active':
            raise ValueError('Эта работа ещё не сдана.')
        return s
    if action == 'finalize':
        return engine.finalize(p['id'], p['teacher'], p['grade'], p['conclusion'], p['decisions'])
    raise ValueError('Неизвестное действие.')


def make_server(engine, port=8877):
    lock = threading.Lock()
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, code, body, mime='application/json; charset=utf-8'):
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            self.end_headers()
            self.wfile.write(body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode())

        def local_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            if not self.local_host():
                self.respond(403, {'error': 'Доступ только через 127.0.0.1.'}); return
            if self.path == '/health':
                self.respond(200, {'app': 'ai-project-ui', 'root': str(ROOT)}); return
            names = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/app.css': ('app.css', 'text/css'), '/workflows.js': ('workflows.js', 'text/javascript')}
            if self.path not in names:
                self.respond(404, {'error': 'Не найдено'}); return
            name, mime = names[self.path]
            body = (ROOT / 'ui' / name).read_text(encoding='utf-8').replace('__TOKEN__', token)
            self.respond(200, body.encode(), mime + '; charset=utf-8')

        def do_POST(self):
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
                self.respond(200, {'result': result})
            except (ValueError, KeyError, TypeError, FileNotFoundError) as exc:
                self.respond(400, {'error': str(exc) if isinstance(exc, ValueError) else 'Данные не найдены или имеют неверный формат.'})
            except RuntimeError as exc:
                self.respond(502, {'error': str(exc)})
            except Exception:
                self.respond(500, {'error': 'Не удалось выполнить действие. Сохранённые работы доступны после обновления страницы.'})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8877)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--data-dir')
    args = parser.parse_args()
    engine = Engine(GigaChat(), args.data_dir)
    try:
        server = make_server(engine, args.port)
    except OSError:
        if not args.no_browser and not args.data_dir:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/health', timeout=2) as r:
                    status = json.load(r)
                if status == {'app': 'ai-project-ui', 'root': str(ROOT)}:
                    webbrowser.open(f'http://127.0.0.1:{args.port}'); return
            except Exception:
                pass
        server = make_server(engine, 0)
    url = f'http://127.0.0.1:{server.server_port}'
    if not args.no_browser:
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
        raise
