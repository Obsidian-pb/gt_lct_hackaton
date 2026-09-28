import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import ai_rest_client

TOKEN = 'gateway-test-token-abcdefghijklmnopqrstuvwxyz'


class CaptureServer(ThreadingHTTPServer):
    def __init__(self, address):
        super().__init__(address, CaptureHandler)
        self.last = None
        self.mode = 'ok'


class CaptureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/health':
            raw = b'{"status":"ok"}'
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        self.send_response(404); self.end_headers()

    def do_POST(self):
        size = int(self.headers.get('Content-Length','0'))
        data = json.loads(self.rfile.read(size).decode('utf-8'))
        self.server.last = {'path': self.path, 'authorization': self.headers.get('Authorization'), 'data': data}
        if self.server.mode == 'unauthorized':
            body = {'error': {'code':'unauthorized','message':'bad token'}, 'request_id':'x'}; status=401
        else:
            body = {'reply':'Лесная, дом 15.'}; status=200
        raw = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.server = CaptureServer(('127.0.0.1', 0))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.env = patch.dict(os.environ, {
            'AI_DIALOGUE_REST_URL': f'http://127.0.0.1:{self.server.server_port}',
            'AI_REST_TOKEN': TOKEN,
            'AI_DIALOGUE_REST_TIMEOUT': '5',
        }, clear=False); self.env.start(); self.addCleanup(self.env.stop)
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)

    def test_server_to_server_payload_and_token(self):
        card = {'report':'Лесная, 15', 'fields':{}}
        fields = {'street':'Сосновая', '_report':'ошибка'}
        turns = [{'role':'dispatcher','text':'Где?'},{'role':'caller','text':'На улице.'}]
        result = ai_rest_client.caller_reply(card=card, student_fields=fields, turns=turns, question='Адрес?')
        self.assertEqual(result, {'reply':'Лесная, дом 15.'})
        self.assertEqual(self.server.last['path'], '/v1/cards/replies')
        self.assertEqual(self.server.last['authorization'], 'Bearer ' + TOKEN)
        self.assertEqual(self.server.last['data']['student_fields'], fields)
        self.assertEqual(self.server.last['data']['turns'], turns)
        self.assertEqual(self.server.last['data']['card'], card)
        self.assertEqual(ai_rest_client.health()['state'], 'available')

    def test_unauthorized_is_clear_gateway_error(self):
        self.server.mode = 'unauthorized'
        with self.assertRaisesRegex(RuntimeError, 'AI_REST_TOKEN'):
            ai_rest_client.caller_reply(card={'report':'x','fields':{}}, student_fields={}, turns=[], question='Где?')


if __name__ == '__main__':
    unittest.main()
