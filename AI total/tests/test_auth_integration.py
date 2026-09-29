"""Integration tests for the auth layer against the live PostgreSQL.

All cases use uniquely-named throwaway records and clean up after themselves.
The suite is skipped entirely when the database is unreachable.
"""
import threading
import unittest
import uuid

try:
    import db_config
    import db_connection
    db_connection.connect_from_config(db_config.get_db_config()).close()
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

if DB_AVAILABLE:
    import auth_repository
    import auth_service
    from rest_api import RestAPI


def _api(router, method, path, body=None, authorization=''):
    return router.handle(method, path, body if body is not None else {}, authorization=authorization)


@unittest.skipUnless(DB_AVAILABLE, 'PostgreSQL недоступен — интеграционные тесты auth пропущены.')
class AuthLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth_repository.AuthRepository().ensure_schema()
        cls.router = RestAPI(None, threading.Lock())
        cls.suffix = uuid.uuid4().hex[:8]

    def setUp(self):
        auth_service.seed_admin()
        self.created_user_ids = []
        self.created_group_ids = []

    def tearDown(self):
        admin = _api(self.router, 'POST', '/api/v1/auth/login',
                     {'login': 'admin', 'password': 'admin123'})
        token = 'Bearer ' + admin.data['access_token']
        for group_id in self.created_group_ids:
            try:
                _api(self.router, 'DELETE', f'/api/v1/auth/groups/{group_id}', {}, authorization=token)
            except Exception:
                pass
        for user_id in self.created_user_ids:
            try:
                _api(self.router, 'DELETE', f'/api/v1/auth/users/{user_id}', {}, authorization=token)
            except Exception:
                pass

    def _create_user(self, token, role='student', password='pass12345'):
        login = f'itest_{role}_{self.suffix}_{uuid.uuid4().hex[:6]}'
        response = _api(self.router, 'POST', '/api/v1/auth/users',
                        {'login': login, 'password': password, 'full_name': 'Тест Юзер', 'role': role},
                        authorization=token)
        self.assertEqual(response.status, 201, response.data)
        self.created_user_ids.append(response.data['id'])
        return response.data, password

    def test_admin_login_and_me(self):
        pair = _api(self.router, 'POST', '/api/v1/auth/login',
                    {'login': 'admin', 'password': 'admin123'})
        self.assertEqual(pair.status, 200)
        self.assertEqual(pair.data['user']['role'], 'admin')
        self.assertTrue(pair.data['access_token'])
        self.assertTrue(pair.data['refresh_token'])
        me = _api(self.router, 'GET', '/api/v1/auth/me',
                  authorization='Bearer ' + pair.data['access_token'])
        self.assertEqual(me.status, 200)
        self.assertEqual(me.data['login'], 'admin')
        self.assertNotIn('password_hash', me.data)

    def test_wrong_password(self):
        from rest_api import APIError
        # Password must pass schema validation (>= 6 chars) to reach the service.
        with self.assertRaises(APIError) as ctx:
            _api(self.router, 'POST', '/api/v1/auth/login', {'login': 'admin', 'password': 'wrong-pass'})
        self.assertEqual(ctx.exception.status, 401)
        self.assertEqual(ctx.exception.code, 'wrong_credentials')

    def test_me_without_token(self):
        from rest_api import APIError
        with self.assertRaises(APIError) as ctx:
            _api(self.router, 'GET', '/api/v1/auth/me')
        self.assertEqual(ctx.exception.status, 401)

    def test_student_cannot_list_users(self):
        from rest_api import APIError
        admin = _api(self.router, 'POST', '/api/v1/auth/login', {'login': 'admin', 'password': 'admin123'})
        token = 'Bearer ' + admin.data['access_token']
        student, password = self._create_user(token, role='student')
        student_pair = _api(self.router, 'POST', '/api/v1/auth/login',
                            {'login': student['login'], 'password': password})
        with self.assertRaises(APIError) as ctx:
            _api(self.router, 'GET', '/api/v1/auth/users',
                 authorization='Bearer ' + student_pair.data['access_token'])
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, 'forbidden')

    def test_users_crud(self):
        admin = _api(self.router, 'POST', '/api/v1/auth/login', {'login': 'admin', 'password': 'admin123'})
        token = 'Bearer ' + admin.data['access_token']
        teacher, password = self._create_user(token, role='teacher')
        user_id = teacher['id']
        updated = _api(self.router, 'PUT', f'/api/v1/auth/users/{user_id}',
                       {'full_name': 'Иван Иванов', 'is_active': False}, authorization=token)
        self.assertEqual(updated.status, 200)
        self.assertEqual(updated.data['full_name'], 'Иван Иванов')
        self.assertFalse(updated.data['is_active'])
        listing = _api(self.router, 'GET', '/api/v1/auth/users', authorization=token)
        ids = [row['id'] for row in listing.data]
        self.assertIn(user_id, ids)

    def test_refresh_rotation_and_logout(self):
        from rest_api import APIError
        pair = _api(self.router, 'POST', '/api/v1/auth/login', {'login': 'admin', 'password': 'admin123'})
        refreshed = _api(self.router, 'POST', '/api/v1/auth/refresh',
                         {'refresh_token': pair.data['refresh_token']})
        self.assertEqual(refreshed.status, 200)
        self.assertTrue(refreshed.data['access_token'])
        # The old refresh token must be revoked by rotation.
        with self.assertRaises(APIError) as ctx:
            _api(self.router, 'POST', '/api/v1/auth/refresh',
                 {'refresh_token': pair.data['refresh_token']})
        self.assertEqual(ctx.exception.status, 401)
        # Logout revokes the second refresh token.
        _api(self.router, 'POST', '/api/v1/auth/logout', {'refresh_token': refreshed.data['refresh_token']})
        with self.assertRaises(APIError) as ctx:
            _api(self.router, 'POST', '/api/v1/auth/refresh',
                 {'refresh_token': refreshed.data['refresh_token']})
        self.assertEqual(ctx.exception.status, 401)

    def test_groups_crud_and_members(self):
        admin = _api(self.router, 'POST', '/api/v1/auth/login', {'login': 'admin', 'password': 'admin123'})
        token = 'Bearer ' + admin.data['access_token']
        name = f'Группа {self.suffix}'
        group = _api(self.router, 'POST', '/api/v1/auth/groups', {'name': name}, authorization=token)
        self.assertEqual(group.status, 201)
        group_id = group.data['id']
        self.created_group_ids.append(group_id)
        student, _password = self._create_user(token, role='student')
        added = _api(self.router, 'POST', f'/api/v1/auth/groups/{group_id}/members',
                     {'user_id': str(student['id'])}, authorization=token)
        self.assertEqual(added.status, 201)
        members = _api(self.router, 'GET', f'/api/v1/auth/groups/{group_id}/members',
                       authorization=token)
        self.assertEqual([row['id'] for row in members.data], [student['id']])
        removed = _api(self.router, 'DELETE', f'/api/v1/auth/groups/{group_id}/members/{student["id"]}',
                       {}, authorization=token)
        self.assertEqual(removed.status, 200)
        groups = _api(self.router, 'GET', '/api/v1/auth/groups', authorization=token)
        self.assertIn(group_id, [row['id'] for row in groups.data])


if __name__ == '__main__':
    unittest.main()