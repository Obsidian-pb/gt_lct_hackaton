"""Independent GigaChat adapter. Never stores credentials in exercise files."""
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class GigaChat:
    def __init__(self):
        local = Path(__file__).with_name('config.local.json')
        team = Path(__file__).with_name('config.team.json')
        shared = Path(os.environ.get('APPDATA', str(Path.home()))) / 'FireSimulation/gigachat_config.json'
        explicit = os.environ.get('AI_PROJECT_CONFIG') or os.environ.get('FIRE_SIM_GIGACHAT_CONFIG')
        if explicit:
            path = Path(explicit)
        elif local.exists():
            path = local
        elif team.exists():
            path = team
        else:
            path = shared
        self.config = json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
        self.key = os.environ.get('GIGACHAT_CREDENTIALS') or os.environ.get('FIRE_SIM_GIGACHAT_AUTHORIZATION_KEY') or self.config.get('authorization_key') or self.config.get('credentials')
        self.model = os.environ.get('AI_PROJECT_MODEL') or self.config.get('model', 'pro')
        self.base = self.config.get('base_url', 'https://api.giga.chat/v1').rstrip('/')
        self.oauth = self.config.get('oauth_url', 'https://ngw.devices.sberbank.ru:9443/api/v2/oauth')
        if not self.base.startswith('https://') or not self.oauth.startswith('https://'):
            raise ValueError('GigaChat: адреса подключения должны использовать HTTPS.')
        verify = self.config.get('verify_ssl', True)
        self.context = ssl.create_default_context(cafile=self.config.get('ca_bundle') or None)
        if verify is False or str(verify).lower() == 'false':
            self.context.check_hostname = False
            self.context.verify_mode = ssl.CERT_NONE
        self.token = ''
        self.expires = 0

    def _request(self, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=75) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # Do not print provider bodies, which may contain request contents.
            raise RuntimeError(f'GigaChat: HTTP {exc.code}. Проверьте доступ, модель и лимиты.') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError('GigaChat: нет ответа или ошибка защищённого соединения. Проверьте интернет и сертификаты.') from None

    def _authorize(self):
        if not self.key:
            raise RuntimeError('Ключ GigaChat не найден. См. README.md: настройка подключения.')
        if self.token and time.time() < self.expires - 60:
            return
        result = self._request(self.oauth, urllib.parse.urlencode({'scope': self.config.get('scope', 'GIGACHAT_API_PERS')}).encode(),
                               {'Authorization': 'Basic ' + self.key, 'RqUID': str(uuid.uuid4()), 'Content-Type': 'application/x-www-form-urlencoded'})
        self.token = result['access_token']
        self.expires = float(result.get('expires_at', time.time() + 1700))
        if self.expires > 10**11:
            self.expires /= 1000
        if self.model.lower() in ('pro', 'auto', 'default'):
            items = self._request(self.base + '/models', headers={'Authorization': 'Bearer ' + self.token}).get('data', [])
            names = [x['id'] for x in items if 'pro' in x.get('id', '').lower()]
            if not names:
                raise RuntimeError('Доступная Pro-модель не найдена. Укажите точное имя доступной модели в AI_PROJECT_MODEL.')
            self.model = next((x for x in names if x == 'GigaChat-2-Pro'), names[0])

    def generate(self, system, payload, temperature=0.3, schema=None):
        self._authorize()
        body = {'model': self.model, 'stream': False, 'temperature': temperature, 'max_tokens': 4500,
                'messages': [{'role': 'system', 'content': system + '\nВерни только JSON-объект, без Markdown.'},
                             {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]}
        if schema:
            body['response_format'] = {'type': 'json_schema', 'schema': schema, 'strict': True}
        result = self._request(self.base + '/chat/completions', json.dumps(body, ensure_ascii=False).encode('utf-8'),
                               {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            text = result['choices'][0]['message']['content'].strip()
            start, end = text.find('{'), text.rfind('}')
            parsed = json.loads(text[start:end + 1])
            if not isinstance(parsed, dict):
                raise ValueError()
            return parsed
        except (ValueError, KeyError, IndexError, TypeError):
            raise RuntimeError('ИИ вернул ответ неверного формата. Работа сохранена; повторите действие.') from None
