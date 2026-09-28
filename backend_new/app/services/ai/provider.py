"""AI adapters for OpenAI, GigaChat, Gemini, Claude and compatible APIs.

Credentials stay in the Python process and are sent only to the configured API.
Configuration sources (priority order): explicit overrides from backend
Settings (.env), AI_* environment variables, JSON config file
(config.local.json next to this module or legacy APPDATA locations).
The GigaChat alias and old configuration variables remain supported.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

SCOPES = ('GIGACHAT_API_PERS', 'GIGACHAT_API_B2B', 'GIGACHAT_API_CORP')
MODEL_PRIORITY = ('GigaChat-2-Pro', 'GigaChat-2-Max', 'GigaChat-3-Ultra', 'GigaChat-2', 'GigaChat')
PROVIDERS = {
    'openai': ('OpenAI', 'https://api.openai.com/v1'),
    'gigachat': ('GigaChat', 'https://api.giga.chat/v1'),
    'gemini': ('Gemini', 'https://generativelanguage.googleapis.com/v1beta/openai'),
    'anthropic': ('Claude', 'https://api.anthropic.com/v1'),
    'openai_compatible': ('OpenAI-совместимый API', ''),
}
AUTO = ('', 'auto', 'default', 'pro')


class ProviderHTTPError(RuntimeError):
    def __init__(self, status: int, code=None, param=None):
        self.status = int(status)
        # Never retain raw provider messages: they can echo credentials or prompts.
        self.code = code if code in ('insufficient_quota', 'model_not_found', 'invalid_api_key') else None
        self.param = param if param in ('response_format', 'temperature', 'max_tokens', 'max_completion_tokens') else None
        super().__init__(f'HTTP {self.status}')


class NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib can forward Authorization and x-api-key on redirects.
        return None


def infer_provider(key, config):
    """Migrate old configurations locally, without trying a key on several services."""
    explicit = str(config.get('provider') or '').strip().lower().replace('-', '_')
    if explicit and explicit != 'auto':
        return explicit
    base = str(config.get('base_url') or '').rstrip('/')
    for name, (_, endpoint) in PROVIDERS.items():
        if endpoint and base == endpoint:
            return name
    if base:
        return 'openai_compatible'
    if key.startswith('sk-ant-'):
        return 'anthropic'
    if key.startswith(('sk-proj-', 'sk-svcacct-')):
        return 'openai'
    if key.startswith('AIza'):
        return 'gemini'
    if key.startswith('sk-'):
        raise ValueError('ИИ: выберите провайдера в настройках backend_new (AI_PROVIDER). По префиксу sk- нельзя отличить OpenAI от других сервисов.')
    return 'gigachat'  # legacy configurations contained GigaChat credentials


def validate_url(value):
    try:
        parsed = urllib.parse.urlsplit(value)
        valid = (parsed.scheme == 'https' and parsed.hostname and parsed.port != 0
                 and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                 and not re.search(r'[\s\x00-\x1f\x7f]', value))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError('ИИ: укажите базовый HTTPS-адрес API без ключа, параметров и пароля.')
    return value.rstrip('/')


def _read_config_file():
    """Legacy file-based configuration, still supported alongside .env."""
    root = Path(__file__).resolve().parent
    appdata = Path(os.environ.get('APPDATA', str(Path.home()))) / 'FireSimulation'
    configured = (os.environ.get('AI_PROJECT_CONFIG') or os.environ.get('AI_PROVIDER_CONFIG')
                  or os.environ.get('FIRE_SIM_GIGACHAT_CONFIG'))
    if configured:
        path = Path(configured)
    elif (root / 'config.local.json').is_file():
        path = root / 'config.local.json'
    elif (appdata / 'ai_config.json').is_file():
        path = appdata / 'ai_config.json'
    else:
        path = appdata / 'gigachat_config.json'
    if not path.is_file():
        return {}
    try:
        config = json.loads(path.read_text(encoding='utf-8-sig'))
        return config if isinstance(config, dict) else {}
    except (ValueError, OSError):
        return {}


class AIProvider:
    def __init__(self, overrides: dict | None = None):
        root = Path(__file__).resolve().parent
        overrides = {k: v for k, v in (overrides or {}).items() if v not in (None, '')}
        file_config = _read_config_file()
        config = dict(file_config)
        for source in (overrides,):
            config.update({k: v for k, v in source.items() if k != 'config_file'})
        raw_key = (os.environ.get('AI_AUTHORIZATION_KEY') or os.environ.get('GIGACHAT_CREDENTIALS')
                   or os.environ.get('FIRE_SIM_GIGACHAT_AUTHORIZATION_KEY')
                   or config.get('authorization_key') or config.get('credentials') or '')
        if not isinstance(raw_key, str):
            raise ValueError('ИИ: ключ должен быть строкой.')
        self.key = re.sub(r'^(Basic|Bearer)\s+', '', raw_key.strip(), flags=re.I).strip()
        if len(self.key) > 16000 or re.search(r'[^\x21-\x7e]', self.key):
            raise ValueError('ИИ: ключ содержит пробелы или недопустимые символы. Вставьте API-ключ одной строкой в AI_API_KEY (.env) или config.local.json.')
        if os.environ.get('AI_PROVIDER'):
            config['provider'] = os.environ['AI_PROVIDER']
        if os.environ.get('AI_BASE_URL'):
            config['base_url'] = os.environ['AI_BASE_URL']
        self.provider = infer_provider(self.key, config)
        if self.provider not in PROVIDERS:
            raise ValueError('ИИ: неизвестный провайдер. Проверьте настройку AI_PROVIDER в .env.')
        self.label, default_base = PROVIDERS[self.provider]
        # Official presets cannot accidentally send credentials to a stale custom URL.
        custom_base = config.get('base_url')
        if self.provider not in ('gigachat', 'openai_compatible') and custom_base and custom_base.rstrip('/') != default_base:
            raise ValueError('ИИ: адрес не соответствует выбранному провайдеру. Для собственного адреса выберите OpenAI-совместимый API.')
        self.base = validate_url(custom_base or default_base)
        self.oauth = validate_url(config.get('oauth_url') or 'https://ngw.devices.sberbank.ru:9443/api/v2/oauth') if self.provider == 'gigachat' else None
        self.requested_model = str(os.environ.get('AI_PROJECT_MODEL') or os.environ.get('AI_MODEL')
                                   or config.get('model') or 'auto').strip()
        if not config.get('provider') and self.provider != 'gigachat' and self.requested_model.startswith('GigaChat'):
            self.requested_model = 'auto'
        self.model = self.requested_model
        self.requested_scope = os.environ.get('AI_SCOPE') or config.get('scope', 'auto')
        self.scope = None
        if self.provider == 'openai_compatible' and self.requested_model.lower() in AUTO:
            raise ValueError('ИИ: для совместимого API укажите точное имя текстовой модели (AI_MODEL в .env).')
        self.context = ssl.create_default_context()
        verify = config.get('verify_ssl', True)
        if verify is False or str(verify).lower() == 'false':
            self.context.check_hostname = False
            self.context.verify_mode = ssl.CERT_NONE
        else:
            configured_ca = os.environ.get('AI_CA_BUNDLE') or config.get('ca_bundle')
            ca_path = Path(configured_ca) if configured_ca else root / 'certs' / 'ai_provider_root_ca.pem' if self.provider == 'gigachat' else None
            if ca_path and ca_path.is_file():
                self.context.load_verify_locations(cafile=str(ca_path))
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.context), NoCredentialRedirect())
        self.token = ''
        self.expires = 0.0
        self._models = []

    def _request(self, url, data=None, headers=None, timeout=75):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with self.opener.open(req, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                details = json.loads(exc.read(16384)).get('error', {})
                if not isinstance(details, dict):
                    details = {}
            except (ValueError, OSError, AttributeError):
                details = {}
            raise ProviderHTTPError(exc.code, details.get('code'), details.get('param')) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError) or 'certificate verify failed' in str(exc.reason).lower():
                hint = ' Проверьте доверенные сертификаты Windows/прокси или задайте AI_CA_BUNDLE.'
                raise RuntimeError(f'ИИ ({self.label}): не удалось проверить защищённое соединение.' + hint) from None
            raise RuntimeError(f'ИИ ({self.label}): нет ответа. Проверьте интернет и доступ к API.') from None
        except (TimeoutError, OSError):
            raise RuntimeError(f'ИИ ({self.label}): сервис не ответил вовремя. Повторите запрос.') from None
        except (ValueError, UnicodeError):
            raise RuntimeError(f'ИИ ({self.label}): сервис вернул не JSON. Проверьте базовый адрес API.') from None

    def _http_error(self, exc):
        status = exc.status
        if status == 401 or exc.code == 'invalid_api_key':
            message = 'ключ API не принят. Проверьте провайдера и ключ в настройках (.env, AI_API_KEY).'
        elif status == 403:
            message = 'доступ запрещён. Проверьте права ключа, доступ к модели и ограничения сервиса.'
        elif status == 429:
            message = ('исчерпана квота API. Проверьте баланс и лимиты в кабинете провайдера.' if exc.code == 'insufficient_quota'
                       else 'превышен лимит запросов или квота API. Проверьте баланс/лимиты и повторите позже.')
        elif status == 402:
            message = 'API требует оплаты. Проверьте баланс у провайдера.'
        elif status == 404 or exc.code == 'model_not_found':
            message = 'не найдены модель или адрес API. Проверьте имя модели и базовый URL.'
        elif status in (400, 422):
            message = 'модель отклонила параметры запроса. Проверьте, что она поддерживает текстовый Chat Completions API и JSON.'
        elif 300 <= status < 400:
            message = 'API вернул перенаправление. Укажите конечный HTTPS-адрес сервиса.'
        elif status >= 500:
            message = 'временная ошибка сервиса. Повторите запрос позже.'
        else:
            message = 'запрос отклонён сервисом. Проверьте настройки подключения.'
        return RuntimeError(f'ИИ ({self.label}), HTTP {status}: {message}')

    def _headers(self):
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if self.provider == 'anthropic':
            headers.update({'x-api-key': self.key, 'anthropic-version': '2023-06-01'})
        else:
            headers['Authorization'] = 'Bearer ' + (self.token if self.provider == 'gigachat' else self.key)
        return headers

    def _scope_candidates(self):
        requested = str(self.requested_scope or 'auto').strip()
        return (requested,) + tuple(s for s in SCOPES if s != requested) if requested in SCOPES else SCOPES

    def _authorize(self):
        if not self.key:
            raise RuntimeError('Ключ ИИ не найден. Задайте AI_API_KEY в .env backend_new или config.local.json.')
        if self.provider == 'gigachat':
            if self.key.startswith(('sk-', 'AIza')):
                raise RuntimeError('ИИ: выбран GigaChat, но ключ похож на ключ другого сервиса. Проверьте настройку AI_PROVIDER.')
            if self.token and time.time() < self.expires - 60:
                if self.model.lower() in AUTO:
                    self._select_model()
                return
            for scope in self._scope_candidates():
                try:
                    result = self._request(self.oauth, urllib.parse.urlencode({'scope': scope}).encode(), {
                        'Authorization': 'Basic ' + self.key, 'RqUID': str(uuid.uuid4()),
                        'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
                except ProviderHTTPError as exc:
                    if exc.status in (400, 401, 403):
                        continue
                    raise self._http_error(exc) from None
                try:
                    token = result['access_token']
                    expires = float(result.get('expires_at', time.time() + 1700))
                    if not isinstance(token, str) or not token:
                        raise ValueError()
                except (KeyError, TypeError, ValueError):
                    raise RuntimeError('ИИ (GigaChat): сервис не вернул токен доступа.') from None
                self.scope, self.token = scope, token
                self.expires = expires / 1000 if expires > 10**11 else expires
                break
            else:
                raise RuntimeError('ИИ (GigaChat): авторизация отклонена. Проверьте ключ авторизации GigaChat и тип доступа (scope).')
        elif self.provider == 'openai' and self.key.startswith(('sk-ant-', 'AIza')):
            raise RuntimeError('ИИ: ключ относится к другому сервису. Проверьте настройку AI_PROVIDER.')
        if self.model.lower() in AUTO:
            self._select_model()

    def _get_models(self):
        result = self._request(self.base + '/models', headers=self._headers())
        if not isinstance(result, dict) or not isinstance(result.get('data'), list):
            raise RuntimeError(f'ИИ ({self.label}): неверный формат списка моделей. Проверьте адрес API.')
        self._models = [x['id'] for x in result['data'] if isinstance(x, dict) and isinstance(x.get('id'), str)]
        return self._models

    def _select_model(self):
        try:
            names = self._get_models()
        except ProviderHTTPError as exc:
            raise self._http_error(exc) from None
        if self.provider == 'gigachat':
            priority = MODEL_PRIORITY
        elif self.provider == 'openai':
            priority = ('gpt-4.1-mini', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4o')
        elif self.provider == 'gemini':
            priority = tuple(sorted((n for n in names if n.startswith('gemini-') and 'flash' in n
                                     and not any(x in n for x in ('image', 'audio', 'live', 'tts', 'embedding', 'preview', 'exp'))), reverse=True))
        elif self.provider == 'anthropic':
            priority = tuple(sorted((n for n in names if n.startswith('claude-') and 'haiku' in n), reverse=True))
        else:
            priority = ()
        for name in priority:
            if name in names:
                self.model = name
                return
        # Do not choose an arbitrary expensive or non-chat model from /models.
        raise RuntimeError(f'ИИ ({self.label}): автоматическая модель недоступна. Укажите доступную текстовую модель (AI_MODEL в .env).')

    def status(self):
        self._authorize()
        try:
            self._get_models()  # explicit models also need a real network check
        except ProviderHTTPError as exc:
            if self.provider == 'openai_compatible' and exc.status in (404, 405, 501):
                return {'state': 'configured', 'message': 'Настройки сохранены. Этот API не поддерживает проверку списка моделей; ключ и генерация ещё не проверены.',
                        'provider': self.provider, 'model': self.model, 'model_selected': True, 'scope_detected': False}
            raise self._http_error(exc) from None
        return {'state': 'available', 'message': f'API {self.label} отвечает. Модель: {self.model}. Генерация и квота ещё не проверены.',
                'provider': self.provider, 'model': self.model, 'model_selected': True, 'scope_detected': bool(self.scope)}

    def generate(self, system, payload, temperature=0.3, schema=None):
        self._authorize()
        instruction = system + '\nВерни только JSON-объект, без Markdown.'
        if schema:
            # Also supplies the contract when a provider has no structured-output support.
            instruction += '\nСоблюдай JSON Schema: ' + json.dumps(schema, ensure_ascii=False)
        user = {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}
        body = {'model': self.model, 'stream': False, 'temperature': temperature, 'max_tokens': 4500}
        if self.provider == 'anthropic':
            body.update(system=instruction, messages=[user])
            endpoint = '/messages'
        else:
            body['messages'] = [{'role': 'system', 'content': instruction}, user]
            endpoint = '/chat/completions'
            if self.provider == 'openai':
                body['max_completion_tokens'] = body.pop('max_tokens')
                # Reasoning families can reject a non-default temperature.
                if re.match(r'^(o\d|gpt-[5-9])', self.model):
                    body.pop('temperature')
            if schema:
                body['response_format'] = ({'type': 'json_schema', 'schema': schema, 'strict': True}
                                           if self.provider == 'gigachat' else
                                           {'type': 'json_schema', 'json_schema': {'name': 'training_response', 'schema': schema, 'strict': True}})
        for attempt in range(3):
            try:
                result = self._request(self.base + endpoint, json.dumps(body, ensure_ascii=False).encode('utf-8'), self._headers())
                break
            except ProviderHTTPError as exc:
                if attempt < 2 and exc.status in (400, 422):
                    if exc.param == 'temperature' and 'temperature' in body:
                        body.pop('temperature')
                        continue
                    if 'response_format' in body and exc.param in (None, 'response_format'):
                        body.pop('response_format')
                        continue
                raise self._http_error(exc) from None
        try:
            if self.provider == 'anthropic':
                if result.get('stop_reason') == 'max_tokens':
                    raise RuntimeError('ИИ: ответ обрезан по лимиту токенов. Уменьшите объём задания или выберите другую модель.')
                text = ''.join(x['text'] for x in result['content'] if x.get('type') == 'text')
            else:
                choice = result['choices'][0]
                if choice.get('finish_reason') == 'length':
                    raise RuntimeError('ИИ: ответ обрезан по лимиту токенов. Уменьшите объём задания или выберите другую модель.')
                if choice['message'].get('refusal') or choice.get('finish_reason') == 'content_filter':
                    raise RuntimeError('ИИ: сервис отказался обрабатывать запрос. Уточните формулировку учебного задания.')
                text = choice['message']['content']
            text = text.strip()
            if text.startswith('```'):
                text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.I)
                text = re.sub(r'\s*```$', '', text)
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError()
            return parsed
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise RuntimeError('ИИ вернул ответ неверного формата. Работа сохранена; повторите действие.') from None


GigaChat = AIProvider