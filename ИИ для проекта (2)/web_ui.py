"""Local single-user browser client for the independent training engine."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import threading
import urllib.request
import webbrowser
from datetime import datetime

from ai_core import Engine, FIELDS, LEVELS, VERDICTS, validate_task, require_text
from provider import GigaChat
from dds import WORKFLOWS, ACTION_LABELS
import card_factory
import card_reference
import card_caller
import teacher_portal

ROOT = Path(__file__).resolve().parent


def student_portal_view(engine, identifier):
    view = engine.student_view(identifier)
    session = engine.load(identifier)
    view['training'] = session.get('training')
    view['reference'] = ({key: row['expected'] for key, row in session['task']['fields'].items()}
                         if session['status'] == 'reviewed' else None)
    view['duration_seconds'] = (max(0, int((datetime.fromisoformat(session['submitted_at']) -
                                           datetime.fromisoformat(session['created_at'])).total_seconds()))
                                if session.get('submitted_at') else None)
    return view


def dispatch(engine, action, p):
    if action in ('teacher_dashboard', 'teacher_session', 'teacher_task', 'teacher_note', 'teacher_finish', 'teacher_launch'):
        return teacher_portal.dispatch(engine, action, p)
    if action == 'student_overview':
        student = require_text(p.get('student'), 'Имя обучающегося', 160)
        sessions = [s for s in engine.list_items('s') if s['student'] == student]
        return {'fields': FIELDS, 'levels': LEVELS,
                'tasks': [{'id': t['id'], 'title': t['title'], 'level': t['level'],
                           'workflow': t.get('workflow', 'caller'), 'teacher': t.get('approved_by', ''),
                           'created_at': t.get('approved_at', t['created_at'])} for t in engine.approved_tasks()],
                'sessions': [{'id': s['id'], 'task_id': s['task']['id'], 'title': s['task']['title'],
                              'level': s['task']['level'], 'workflow': s['task'].get('workflow', 'caller'),
                              'status': s['status'], 'created_at': s['created_at'],
                              'teacher': s['task'].get('approved_by', ''),
                              'grade': s['teacher_decision']['grade'] if s['status'] == 'reviewed' else None}
                             for s in sessions]}
    if action == 'student_start':
        student = require_text(p.get('student'), 'Имя обучающегося', 160)
        task_id = p.get('task_id')
        for s in engine.list_items('s'):
            if s['student'] == student and s['task']['id'] == task_id and s['status'] == 'active':
                return student_portal_view(engine, s['id'])
        return student_portal_view(engine, engine.start(task_id, student)['id'])
    if action == 'student_action':
        student = require_text(p.get('student'), 'Имя обучающегося', 160)
        if engine.load(p.get('id'))['student'] != student:
            raise ValueError('Эта тренировка относится к другому обучающемуся.')
        operation = p.get('operation')
        if operation not in ('student', 'ask', 'hint', 'save_card', 'submit', 'connect', 'channel'):
            raise ValueError('Действие недоступно в панели обучающегося.')
        dispatch(engine, operation, p)
        return student_portal_view(engine, p['id'])
    if action == 'teacher_overview':
        return {
            'sessions': [{'id': s['id'], 'title': s['task']['title'], 'student': s['student'],
                          'status': s['status'], 'workflow': s['task'].get('workflow', 'caller'),
                          'created_at': s.get('created_at'),
                          'grade': (s.get('teacher_decision') or {}).get('grade') if s['status'] == 'reviewed' else None}
                         for s in engine.list_items('s')],
            'tasks': [{key: t.get(key) for key in ('id', 'title', 'status', 'workflow', 'level')}
                      for t in engine.list_items('t')],
        }
    if action == 'card_meta':
        return card_factory.metadata()
    if action == 'card_generate':
        return card_factory.generate(engine.provider, p)
    if action == 'card_reference':
        return card_reference.generate(engine.provider, p)
    if action == 'card_caller':
        return card_caller.ask(engine.provider, p)
    if action == 'card_approve':
        return card_factory.approve(p)
    if action == 'card_validate':
        return card_factory.validate_content(p.get('content'))
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


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        # Windows otherwise permits two local copies to share the same port.
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(engine, port=8878):
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
            names = {'/': ('react.html', 'text/html'), '/teacher': ('react.html', 'text/html'),
                     '/student': ('react.html', 'text/html'), '/student.css': ('student.css', 'text/css'),
                     '/theme.css': ('theme.css', 'text/css'),
                     '/workspace.css': ('workspace.css', 'text/css'),
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
            if self.path not in names:
                self.respond(404, {'error': 'Не найдено'}); return
            name, mime = names[self.path]
            body = (ROOT / 'ui' / name).read_text(encoding='utf-8').replace('__TOKEN__', token)
            if name == 'react.html':
                styles = ['/welcome.css'] if self.path == '/' else (['/student.css'] if self.path == '/student' else (['/cards.css', '/teacher.css', '/making.css'] if self.path == '/cards' else ['/teacher.css']))
                body = body.replace('__STYLES__', ''.join(f'<link rel="stylesheet" href="{href}">' for href in ['/theme.css', *styles, *(['/workspace.css'] if self.path == '/teacher' else [])]))
                body = body.replace('__BODY_CLASS__', '' if self.path == '/' else ('student-app' if self.path == '/student' else ('teacher-app cards-page' if self.path == '/cards' else 'teacher-app')))
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

    server = LocalServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8878)
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
