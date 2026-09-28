"""Minimal PostgreSQL wire-protocol client (protocol 3.0) using stdlib only.

Supports SSL negotiation (prefer/require/disable) and password authentication
methods: trust, cleartext, MD5 and SCRAM-SHA-256 (RFC 5802 / RFC 7677).
The project keeps zero third-party Python dependencies, so psycopg2 is
deliberately not used. Besides connecting and authenticating, the client can
execute SQL through the Simple Query protocol (execute/fetchone), escape
literals safely (quote_literal) and run transactional blocks (transaction).
"""
from __future__ import annotations

import base64
import contextlib
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


def quote_literal(value) -> str:
    """Return a safely quoted SQL literal for the Simple Query protocol.

    None becomes NULL, booleans become TRUE/FALSE, numbers stay unquoted and
    strings are wrapped in single quotes with embedded quotes doubled
    (standard_conforming_strings is on since PostgreSQL 9.1, so backslashes
    need no special treatment). NUL bytes are rejected.
    """
    if value is None:
        return 'NULL'
    if value is True or value is False:
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if '\x00' in text:
        raise DbConnectionError('Строковый литерал содержит NUL-байт')
    return "'" + text.replace("'", "''") + "'"


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
        self._command_tag = ''
        self._rowcount = 0
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

    @property
    def command_tag(self) -> str:
        """Server command tag of the last executed statement (e.g. 'INSERT 0 1')."""
        return self._command_tag

    @property
    def rowcount(self) -> int:
        """Affected row count of the last INSERT/UPDATE/DELETE/SELECT statement."""
        return self._rowcount

    # ----------------------------------------------------------------- queries

    def execute(self, sql: str) -> list:
        """Execute SQL via the Simple Query protocol and return all result rows.

        Values arrive in text format and are decoded as UTF-8 (client_encoding
        is set to UTF8 during startup). DDL/DML without RETURNING return an
        empty list; the affected row count is available through self.rowcount
        and the raw command tag through self.command_tag. To pass untrusted
        values safely, embed them with quote_literal().
        """
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError('SQL-запрос не может быть пустым.')
        rows, tag = self._simple_query(sql)
        self._command_tag = tag
        self._rowcount = self._tag_rowcount(tag)
        return rows

    def fetchone(self, sql: str):
        """Execute a query and return the first row or None."""
        rows = self.execute(sql)
        return rows[0] if rows else None

    @contextlib.contextmanager
    def transaction(self):
        """Run a block inside BEGIN/COMMIT, rolling back on any exception.

        Usage:
            with connection.transaction():
                connection.execute("INSERT ...")
        """
        self.execute('BEGIN')
        try:
            yield self
        except BaseException:
            try:
                self.execute('ROLLBACK')
            except DbConnectionError:
                pass
            raise
        else:
            self.execute('COMMIT')

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
        rows, _tag = self._simple_query('SELECT 1')
        if not rows:
            raise DbConnectionError('Запрос проверки SELECT 1 не вернул данных')

    def _simple_query(self, sql: str) -> tuple:
        """Send a Simple Query and consume messages up to ReadyForQuery."""
        self._send_payload(b'Q', sql.encode('utf-8') + b'\x00')
        rows: list = []
        columns: list = []
        tag = ''
        while True:
            code, body = self._read_message()
            if code == b'T':  # RowDescription
                columns = self._parse_row_description(body)
            elif code == b'D':  # DataRow
                rows.append(self._parse_data_row(body))
            elif code == b'C':  # CommandComplete
                tag = body[:-1].decode('utf-8', 'replace')
            elif code == b'I':  # EmptyQueryResponse
                pass
            elif code == b'E':  # ErrorResponse — drain then raise
                error = _error_fields(body)
                while True:
                    code, body = self._read_message()
                    if code == b'Z':
                        break
                raise DbConnectionError(error)
            elif code == b'Z':  # ReadyForQuery
                break
            elif code in (b'S', b'N', b'K'):
                pass
            else:
                raise DbConnectionError(f'Неожиданный ответ сервера: {code.decode("ascii", "replace")}')
        return rows, tag

    def _parse_row_description(self, body: bytes) -> list:
        count = struct.unpack('!h', body[:2])[0]
        columns = []
        offset = 2
        for _ in range(count):
            end = body.index(b'\x00', offset)
            columns.append(body[offset:end].decode('utf-8', 'replace'))
            offset = end + 1 + 18  # oid(4) + attr(2) + type_oid(4) + typlen(2) + typmod(4) + format(2)
        return columns

    def _parse_data_row(self, body: bytes) -> tuple:
        count = struct.unpack('!h', body[:2])[0]
        values = []
        offset = 2
        for _ in range(count):
            length = struct.unpack('!i', body[offset:offset + 4])[0]
            offset += 4
            if length == -1:
                values.append(None)
            else:
                values.append(body[offset:offset + length].decode('utf-8', 'replace'))
                offset += length
        return tuple(values)

    @staticmethod
    def _tag_rowcount(tag: str) -> int:
        parts = tag.split()
        if parts and parts[0] in ('INSERT', 'UPDATE', 'DELETE', 'SELECT', 'MOVE', 'FETCH', 'COPY'):
            try:
                return int(parts[-1])
            except ValueError:
                return 0
        return 0


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
