"""One-use loopback bridge: browser speech recognition -> console transcript."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import webbrowser


def capture(timeout=120, open_browser=True, on_ready=None):
    token = secrets.token_urlsafe(32)
    done = threading.Event()
    result = {'text': ''}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, content_type='text/plain; charset=utf-8'):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != '/' + token:
                self.send(404, b'Not found'); return
            page = Path(__file__).with_name('microphone.html').read_bytes()
            self.send(200, page, 'text/html; charset=utf-8')

        def do_POST(self):
            if self.path != '/' + token or done.is_set():
                self.send(403, b'Expired'); return
            if self.headers.get('Origin') not in (None, f'http://127.0.0.1:{self.server.server_port}'):
                self.send(403, b'Forbidden'); return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16000:
                    raise ValueError()
                data = json.loads(self.rfile.read(size))
                text = data.get('text', '')
                if not isinstance(text, str) or len(text) > 2000:
                    raise ValueError()
            except (ValueError, AttributeError):
                self.send(400, b'Invalid transcript'); return
            result['text'] = text.strip()
            self.send(200, b'OK')
            done.set()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/{token}'
    try:
        print('Окно микрофона (откройте в Chrome или Edge): ' + url)
        print('Нажмите «Включить микрофон», разрешите доступ, проверьте текст и отправьте. Ожидание 2 минуты; Ctrl+C — отмена.')
        if on_ready:
            on_ready(url)
        if open_browser:
            webbrowser.open(url)
        if not done.wait(timeout):
            raise RuntimeError('Время ожидания микрофона истекло. Можно повторить /voice или ввести вопрос текстом.')
        return result['text']
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
