"""Protocol-level tests for the stdlib PostgreSQL client (no live DB)."""
import struct
import unittest
from unittest.mock import patch

import db_connection
from db_connection import DbConnectionError, PostgresConnection


def _message(code, body=b''):
    return code + struct.pack('!i', len(body) + 4) + body


class _FakeSocket:
    def __init__(self, incoming):
        self.incoming = bytearray(incoming)
        self.sent = []

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, size):
        if not self.incoming:
            return b''
        chunk = self.incoming[:size]
        del self.incoming[:size]
        return bytes(chunk)

    def close(self):
        pass


def _row_description(name='result'):
    return (struct.pack('!h', 1) + name.encode('ascii') + b'\x00'
            + struct.pack('!IhIhih', 0, 0, 25, -1, -1, 0))


def _data_row(*values):
    body = struct.pack('!h', len(values))
    for value in values:
        if value is None:
            body += struct.pack('!i', -1)
        else:
            encoded = value.encode('utf-8')
            body += struct.pack('!i', len(encoded)) + encoded
    return body


def _success_response():
    return b''.join((
        _message(b'1'),                 # ParseComplete
        _message(b'2'),                 # BindComplete
        _message(b'T', _row_description()),
        _message(b'D', _data_row('ok')),
        _message(b'C', b'SELECT 1\x00'),
        _message(b'Z', b'I'),           # ReadyForQuery, idle
    ))


def _outbound_messages(packet):
    messages = []
    offset = 0
    while offset < len(packet):
        code = packet[offset:offset + 1]
        length = struct.unpack('!i', packet[offset + 1:offset + 5])[0]
        messages.append((code, packet[offset + 5:offset + 1 + length]))
        offset += length + 1
    return messages


class _FakeConnection(PostgresConnection):
    def __init__(self, **kwargs):
        super().__init__(
            host=kwargs['host'], port=kwargs['port'], dbname=kwargs['dbname'],
            user=kwargs['user'], password=kwargs['password'])
        self._sock = _FakeSocket(b'')
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        self._sock = _FakeSocket(b'')
        self._broken = False


class ConnectionReuseTests(unittest.TestCase):
    def setUp(self):
        db_connection.close_thread_connection()

    def tearDown(self):
        db_connection.close_thread_connection()

    def _config(self, **updates):
        return {'host': 'localhost', 'port': 5432, 'dbname': 'test',
                'user': 'tester', 'password': 'secret', **updates}

    def test_reuses_connection_for_same_config_then_closes_it(self):
        with patch.object(db_connection, 'PostgresConnection', _FakeConnection):
            first = db_connection.connection_from_config(self._config())
            second = db_connection.connection_from_config(self._config())

        self.assertIs(first, second)
        self.assertEqual(first.connect_calls, 1)
        db_connection.close_thread_connection()
        self.assertIsNone(first._sock)
        self.assertIsNone(db_connection._CONNECTION_LOCAL.connection)

    def test_config_change_closes_old_connection(self):
        with patch.object(db_connection, 'PostgresConnection', _FakeConnection):
            first = db_connection.connection_from_config(self._config())
            second = db_connection.connection_from_config(self._config(dbname='other'))

        self.assertIsNot(first, second)
        self.assertIsNone(first._sock)

    def test_broken_cached_connection_is_reconnected(self):
        with patch.object(db_connection, 'PostgresConnection', _FakeConnection):
            connection = db_connection.connection_from_config(self._config())
            connection._broken = True
            reused = db_connection.connection_from_config(self._config())

        self.assertIs(reused, connection)
        self.assertEqual(connection.connect_calls, 2)
        self.assertFalse(connection._broken)


class ExtendedQueryProtocolTests(unittest.TestCase):
    def _connection(self, incoming):
        connection = PostgresConnection('localhost', 5432, 'db', 'user', '')
        connection._sock = _FakeSocket(incoming)
        return connection

    def test_sends_parse_bind_execute_sync_with_text_values_and_null(self):
        connection = self._connection(_success_response())
        rows = connection.execute_params(
            'SELECT $1::text, $2::int, $3::bool, $4::text',
            ('тест', 42, True, None))

        self.assertEqual(rows, [('ok',)])
        self.assertEqual(connection.command_tag, 'SELECT 1')
        self.assertEqual(connection.rowcount, 1)
        messages = _outbound_messages(connection._sock.sent[0])
        self.assertEqual([code for code, _body in messages], [b'P', b'B', b'E', b'S'])

        parse = messages[0][1]
        self.assertTrue(parse.startswith(b'\x00SELECT $1::text'))
        self.assertEqual(parse[-2:], b'\x00\x00')  # no forced parameter types

        bind = messages[1][1]
        self.assertEqual(bind[:2], b'\x00\x00')  # unnamed portal/statement
        self.assertEqual(struct.unpack('!h', bind[2:4])[0], 0)  # format count: all text
        self.assertEqual(struct.unpack('!h', bind[4:6])[0], 4)
        offset = 6
        values = []
        for _ in range(4):
            length = struct.unpack('!i', bind[offset:offset + 4])[0]
            offset += 4
            if length == -1:
                values.append(None)
            else:
                values.append(bind[offset:offset + length])
                offset += length
        self.assertEqual(values, ['тест'.encode('utf-8'), b'42', b'true', None])
        self.assertEqual(bind[offset:], b'\x00\x00')  # zero result format codes
        self.assertEqual(messages[2][1], b'\x00\x00\x00\x00\x00')  # unlimited Execute
        self.assertEqual(messages[3][1], b'')

    def test_parameter_is_separate_from_sql(self):
        connection = self._connection(_success_response())
        malicious = "x'); DROP TABLE users; --"
        connection.execute_params('SELECT $1::text', (malicious,))
        messages = _outbound_messages(connection._sock.sent[0])
        self.assertNotIn(malicious.encode('utf-8'), messages[0][1])
        self.assertIn(malicious.encode('utf-8'), messages[1][1])

    def test_error_drains_to_ready_for_query_and_keeps_connection_usable(self):
        error = b'SERROR\x00C42601\x00Mbad query\x00\x00'
        connection = self._connection(
            _message(b'E', error) + _message(b'Z', b'E') + _success_response())
        with self.assertRaisesRegex(DbConnectionError, 'bad query'):
            connection.execute_params('SELECT $1::text', ('x',))
        self.assertEqual(connection.execute_params('SELECT $1::text', ('y',)), [('ok',)])

    def test_rejects_unsupported_and_nul_values_before_sending(self):
        connection = self._connection(_success_response())
        with self.assertRaises(TypeError):
            connection.execute_params('SELECT $1', (object(),))
        with self.assertRaises(ValueError):
            connection.execute_params('SELECT $1', ('has\x00nul',))
        self.assertEqual(connection._sock.sent, [])


if __name__ == '__main__':
    unittest.main()
