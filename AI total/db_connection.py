"""Minimal PostgreSQL wire-protocol client (protocol 3.0) using stdlib only.

Supports SSL negotiation (prefer/require/disable) and password authentication
methods: trust, cleartext, MD5 and SCRAM-SHA-256 (RFC 5802 / RFC 7677).
The project keeps zero third-party Python dependencies, so psycopg2 is
deliberately not used. This module only opens a verified connection and
closes it; no queries beyond the internal "SELECT 1" verification are run.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import socket
import ssl as _ssl
import struct
from typing import Dict, Optional

PROTOCOL_VERSION = 196608  # 3 << 16
SSL_REQUEST_CODE = 80877103
SCRAM_MECHANISM = 'SCRAM-SHA-256'


class DbConnectionError(RuntimeError):
    """Any failure while connecting, authenticating or verifying."""


def _cstr(value: str) -> bytes:
    return value.encode('utf-8') + b'\x00'


class PostgresConnection:
    def __init__(self, host: str, port: int, dbname: str, user: str, password: str,
                 connect_timeout: float = 10, sslmode: str = 'prefer'):
        self.host = str(host)
        self.port = int(port)
        self.dbname = str(dbname)
        self.user = str(user)
        self.password = str(password)
        self.connect_timeout = float(connect_timeout)
        self.sslmode = str(sslmode).lower()
        self._sock: Optional[socket.socket] = None
        self._buffer = b''
        self._auth_method = ''
        self._server_params: Dict[str, str] = {}
        # SCRAM state kept between the SASL steps.
        self._scram_client_first_bare = ''
        self._scram_auth_message = ''
        self._scram_server_signature = b''

    # ------------------------------------------------------------------ public

    def connect(self) -> None:
        """Open the socket, negotiate SSL, authenticate and wait for readiness."""
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        except OSError as exc:
            raise DbConnectionError(f'Сервер {self.host}:{self.port} недоступен ({_oserror_text(exc)})') from None
        self._sock.settimeout(self.connect_timeout)
        try:
            self._negotiate_ssl()
            self._send_startup()
            self._authenticate_until_ready()
            self._verify_select1()
        except DbConnectionError:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise DbConnectionError(f'Соединение разорвано ({_oserror_text(exc)})') from None

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.sendall(b'X' + struct.pack('!i', 4))
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self) -> 'PostgresConnection':
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @property
    def ssl_active(self) -> bool:
        return isinstance(self._sock, _ssl.SSLSocket)

    @property
    def auth_method(self) -> str:
        return self._auth_method

    @property
    def server_params(self) -> Dict[str, str]:
        return dict(self._server_params)

    # ------------------------------------------------------------------- setup

    def _negotiate_ssl(self) -> None:
        if self.sslmode == 'disable':
            return
        self._sock.sendall(struct.pack('!ii', 8, SSL_REQUEST_CODE))
        response = self._read_exact(1)
        if response == b'S':
            context = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = _ssl.CERT_NONE
            self._sock = context.wrap_socket(self._sock, server_hostname=self.host)
        elif response == b'N':
            if self.sslmode == 'require':
                raise DbConnectionError('Сервер не поддерживает SSL, а требуется sslmode=require')
        else:
            raise DbConnectionError('Некорректный ответ на запрос SSL-негатциации')

    def _send_startup(self) -> None:
        body = struct.pack('!i', PROTOCOL_VERSION)
        for key, value in (('user', self.user), ('database', self.dbname), ('client_encoding', 'UTF8')):
            body += _cstr(key) + _cstr(value)
        body += b'\x00'
        self._sock.sendall(struct.pack('!i', len(body) + 4) + body)

    # ------------------------------------------------------------- message i/o

    def _read_exact(self, size: int) -> bytes:
        while len(self._buffer) < size:
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                raise DbConnectionError('Таймаут ожидания ответа от сервера') from None
            except OSError as exc:
                raise DbConnectionError(f'Ошибка чтения сокета ({_oserror_text(exc)})') from None
            if not chunk:
                raise DbConnectionError('Сервер закрыл соединение во время подключения')
            self._buffer += chunk
        data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data

    def _read_message(self) -> tuple:
        header = self._read_exact(5)
        code = header[:1]
        length = struct.unpack('!i', header[1:])[0]
        if length < 4:
            raise DbConnectionError('Некорректная длина сообщения сервера')
        return code, self._read_exact(length - 4)

    def _send_payload(self, code: bytes, payload: bytes) -> None:
        self._sock.sendall(code + struct.pack('!i', len(payload) + 4) + payload)

    # -------------------------------------------------------------- auth flow

    def _authenticate_until_ready(self) -> None:
        while True:
            code, body = self._read_message()
            if code == b'R':
                self._handle_auth(body)
            elif code == b'S':
                text = body.split(b'\x00')
                if len(text) >= 2:
                    self._server_params[text[0].decode('utf-8', 'replace')] = text[1].decode('utf-8', 'replace')
            elif code == b'K':
                pass  # BackendKeyData
            elif code == b'Z':
                return  # ReadyForQuery
            elif code == b'E':
                raise DbConnectionError(_error_fields(body))
            elif code == b'N':
                pass  # NoticeResponse
            else:
                raise DbConnectionError(f'Неожиданное сообщение сервера: {code.decode("ascii", "replace")}')

    def _handle_auth(self, body: bytes) -> bool:
        """Send the appropriate auth reply; returns True unless AuthenticationOk."""
        request = struct.unpack('!i', body[:4])[0]
        if request == 0:
            self._auth_method = self._auth_method or 'trust'
            return False
        if request == 3:  # cleartext password
            self._auth_method = 'password'
            self._send_payload(b'p', self.password.encode('utf-8') + b'\x00')
            return True
        if request == 5:  # MD5
            self._auth_method = 'md5'
            salt = body[4:8]
            inner = hashlib.md5((self.password + self.user).encode('utf-8')).hexdigest()
            digest = 'md5' + hashlib.md5(inner.encode('ascii') + salt).hexdigest()
            self._send_payload(b'p', digest.encode('ascii') + b'\x00')
            return True
        if request == 10:  # SASL mechanisms
            mechanisms = [m.decode('ascii', 'replace') for m in body[4:].split(b'\x00') if m]
            if SCRAM_MECHANISM not in mechanisms:
                raise DbConnectionError(f'Сервер не поддерживает {SCRAM_MECHANISM}: {mechanisms}')
            self._auth_method = 'scram-sha-256'
            nonce = base64.b64encode(secrets.token_bytes(18)).decode('ascii')
            self._scram_client_first_bare = f'n=,r={nonce}'
            client_first = 'n,,' + self._scram_client_first_bare
            payload = _cstr(SCRAM_MECHANISM) + struct.pack('!i', len(client_first)) + client_first.encode('utf-8')
            self._send_payload(b'p', payload)
            return True
        if request == 11:  # SASLInitialResponse (server-first-message)
            self._scram_send_final(body)
            return True
        if request == 12:  # SASLFinal (server signature)
            self._scram_verify_server(body)
            return False
        raise DbConnectionError(f'Неподдерживаемый метод аутентификации (код {request})')

    # ------------------------------------------------------------------- scram

    def _scram_send_final(self, server_first: bytes) -> None:
        try:
            data = server_first.decode('utf-8')
            attrs = dict(part.split('=', 1) for part in data.split(','))
            combined_nonce = attrs['r']
            salt = base64.b64decode(attrs['s'])
            iterations = int(attrs['i'])
        except (ValueError, KeyError, UnicodeDecodeError):
            raise DbConnectionError('Не удалось разобрать SCRAM-сообщение сервера') from None
        client_nonce = self._scram_client_first_bare.split('r=', 1)[1]
        if not combined_nonce.startswith(client_nonce):
            raise DbConnectionError('SCRAM: nonce сервера не совпадает с клиентским')
        salted = hashlib.pbkdf2_hmac('sha1', self.password.encode('utf-8'), salt, iterations, 32)
        client_key = hmac.new(salted, b'Client Key', hashlib.sha1).digest()
        stored_key = hashlib.sha1(client_key).digest()
        client_final_without_proof = f'c=biws,r={combined_nonce}'
        self._scram_auth_message = f'{self._scram_client_first_bare},{data},{client_final_without_proof}'
        client_signature = hmac.new(stored_key, self._scram_auth_message.encode('utf-8'), hashlib.sha1).digest()
        proof = bytes(a ^ b for a, b in zip(client_key, client_signature))
        client_final = f'{client_final_without_proof},p={base64.b64encode(proof).decode("ascii")}'
        server_key = hmac.new(salted, b'Server Key', hashlib.sha1).digest()
        self._scram_server_signature = hmac.new(server_key, self._scram_auth_message.encode('utf-8'), hashlib.sha1).digest()
        self._send_payload(b'p', client_final.encode('utf-8'))

    def _scram_verify_server(self, sasl_final: bytes) -> None:
        try:
            attrs = dict(part.split('=', 1) for part in sasl_final.decode('utf-8').split(','))
            verifier = base64.b64decode(attrs['v'])
        except (ValueError, KeyError, UnicodeDecodeError):
            raise DbConnectionError('Не удалось разобрать финальное SCRAM-сообщение сервера') from None
        if not hmac.compare_digest(verifier, self._scram_server_signature):
            raise DbConnectionError('SCRAM: подпись сервера не подтверждена')

    # -------------------------------------------------------------- validation

    def _verify_select1(self) -> None:
        """Confirm the session can execute a trivial query."""
        self._send_payload(b'Q', b'SELECT 1\x00')
        completed = False
        while True:
            code, body = self._read_message()
            if code == b'D':
                completed = True
            elif code == b'C':
                pass
            elif code == b'T':
                pass
            elif code == b'Z':
                break
            elif code == b'E':
                raise DbConnectionError('Запрос проверки SELECT 1 отклонён: ' + _error_fields(body))
            elif code in (b'S', b'N', b'K'):
                pass
            else:
                raise DbConnectionError('Неожиданный ответ на запрос проверки сессии')
        if not completed:
            raise DbConnectionError('Запрос проверки SELECT 1 не вернул данных')


def _error_fields(body: bytes) -> str:
    """Parse an ErrorResponse body into a readable single-line message."""
    fields: Dict[str, str] = {}
    parts = body.split(b'\x00')
    for part in parts:
        if len(part) >= 2:
            fields[chr(part[0])] = part[1:].decode('utf-8', 'replace')
    message = fields.get('M', 'неизвестная ошибка сервера')
    detail = fields.get('D')
    source = fields.get('S')
    text = message if not detail else f'{message}. {detail}'
    if source and source not in ('ERROR',):
        text = f'[{source}] {text}'
    return text


def _oserror_text(exc: OSError) -> str:
    strerror = getattr(exc, 'strerror', None)
    if strerror:
        return strerror
    return str(exc)


def connect_from_config(config: Dict[str, object]) -> PostgresConnection:
    """Open and verify a connection using a settings dict from db_config."""
    connection = PostgresConnection(
        host=config.get('host', '127.0.0.1'),
        port=int(config.get('port', 5432)),
        dbname=str(config.get('dbname', '')),
        user=str(config.get('user', '')),
        password=str(config.get('password', '')),
        connect_timeout=float(config.get('connect_timeout', 10)),
        sslmode=str(config.get('sslmode', 'prefer')),
    )
    connection.connect()
    return connection
