"""Integration tests for the catalog layer against the live PostgreSQL.

Schema init is idempotent; classifier import yields 61/24/1283 rows; repeated
import does not duplicate; /catalog/* CRUD works under the admin JWT and is
forbidden for students; deleting a referenced service returns 409. All
throwaway records use unique keys and are removed in tearDown. The suite is
skipped entirely when the database is unreachable.
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
    import auth_service
    import catalog_importer
    import catalog_repository
    from rest_api import RestAPI, APIError


def _api(router, method, path, body=None, authorization=''):
    return router.handle(method, path, body if body is not None else {}, authorization=authorization)


@unittest.skipUnless(DB_AVAILABLE, 'PostgreSQL недоступен — интеграционные тесты catalog пропущены.')
class CatalogLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = catalog_repository.CatalogRepository()
        cls.repo.ensure_schema()          # first run
        cls.repo.ensure_schema()          # idempotency check
        data = catalog_importer.parse_classifier()
        cls.repo.replace_classifier(data['services'], data['categories'],
                                    data['entries'], data['entry_services'])
        cls.router = RestAPI(None, threading.Lock())
        cls.suffix = uuid.uuid4().hex[:8]

    def setUp(self):
        auth_service.seed_admin()
        self.created_services = []
        self.created_categories = []
        self.created_entries = []
        self.created_links = []
        self.created_addresses = []
        self.created_user_ids = []

    def tearDown(self):
        token = 'Bearer ' + _api(self.router, 'POST', '/api/v1/auth/login',
                                 {'login': 'admin', 'password': 'admin123'}).data['access_token']
        for link_id in self.created_links:
            try:
                _api(self.router, 'DELETE', f'/api/v1/catalog/entry-services/{link_id}', {}, authorization=token)
            except Exception:
                pass
        for entry_id in self.created_entries:
            try:
                _api(self.router, 'DELETE', f'/api/v1/catalog/entries/{entry_id}', {}, authorization=token)
            except Exception:
                pass
        for category_id in self.created_categories:
            try:
                _api(self.router, 'DELETE', f'/api/v1/catalog/categories/{category_id}', {}, authorization=token)
            except Exception:
                pass
        for code in self.created_services:
            try:
                _api(self.router, 'DELETE', f'/api/v1/catalog/services/{code}', {}, authorization=token)
            except Exception:
                pass
        for address_id in self.created_addresses:
            try:
                _api(self.router, 'DELETE', f'/api/v1/catalog/geo-addresses/{address_id}', {}, authorization=token)
            except Exception:
                pass
        for user_id in self.created_user_ids:
            try:
                _api(self.router, 'DELETE', f'/api/v1/auth/users/{user_id}', {}, authorization=token)
            except Exception:
                pass

    def _admin_token(self):
        pair = _api(self.router, 'POST', '/api/v1/auth/login',
                    {'login': 'admin', 'password': 'admin123'})
        return 'Bearer ' + pair.data['access_token']

    def _create_student(self):
        login = f'cat_student_{self.suffix}_{uuid.uuid4().hex[:6]}'
        created = _api(self.router, 'POST', '/api/v1/auth/users',
                       {'login': login, 'password': 'pass12345', 'full_name': 'Студент Каталога', 'role': 'student'},
                       authorization=self._admin_token())
        self.created_user_ids.append(created.data['id'])
        pair = _api(self.router, 'POST', '/api/v1/auth/login',
                    {'login': login, 'password': 'pass12345'})
        return 'Bearer ' + pair.data['access_token']

    # -------------------------------------------------------------- schema/import

    def test_import_counts_and_idempotency(self):
        counts = self.repo.counts()
        self.assertEqual(61, counts['services'])
        self.assertEqual(24, counts['categories'])
        self.assertEqual(1283, counts['entries'])
        self.assertGreater(counts['entry_services'], 0)
        # A second import must not grow the tables (replace-all strategy).
        data = catalog_importer.parse_classifier()
        self.repo.replace_classifier(data['services'], data['categories'],
                                     data['entries'], data['entry_services'])
        counts_again = self.repo.counts()
        self.assertEqual(counts, counts_again)
        self.assertEqual('2.2.0', self.repo.migration_version())

    def test_geo_import(self):
        geo = catalog_importer.parse_geo_addresses()
        imported = self.repo.replace_geo(geo['addresses'], geo['buildings'])
        counts = self.repo.counts()
        self.assertEqual(imported['addresses'], counts['geo_addresses'])
        self.assertEqual(imported['buildings'], counts['geo_buildings'])
        self.assertGreater(counts['geo_addresses'], 0)

    # ------------------------------------------------------------------- RBAC

    def test_student_cannot_list_catalog(self):
        student_token = self._create_student()
        with self.assertRaises(APIError) as ctx:
            _api(self.router, 'GET', '/api/v1/catalog/services', authorization=student_token)
        self.assertEqual(403, ctx.exception.status)
        self.assertEqual('forbidden', ctx.exception.code)

    def test_catalog_requires_token(self):
        with self.assertRaises(APIError) as ctx:
            _api(self.router, 'GET', '/api/v1/catalog/services')
        self.assertEqual(401, ctx.exception.status)

    # ------------------------------------------------------------------- CRUD

    def test_services_crud(self):
        token = self._admin_token()
        code = f'T{self.suffix}'
        created = _api(self.router, 'POST', '/api/v1/catalog/services',
                       {'code': code, 'name': 'Тестовая служба'}, authorization=token)
        self.assertEqual(201, created.status)
        self.created_services.append(code)
        updated = _api(self.router, 'PUT', f'/api/v1/catalog/services/{code}',
                       {'name': 'Новое имя'}, authorization=token)
        self.assertEqual('Новое имя', updated.data['name'])
        listing = _api(self.router, 'GET', '/api/v1/catalog/services', authorization=token)
        self.assertIn(code, [row['code'] for row in listing.data])
        duplicate = None
        try:
            _api(self.router, 'POST', '/api/v1/catalog/services',
                 {'code': code, 'name': 'Дубль'}, authorization=token)
        except APIError as exc:
            duplicate = exc
        self.assertIsNotNone(duplicate)
        self.assertEqual(409, duplicate.status)

    def test_categories_crud_and_fk_validation(self):
        token = self._admin_token()
        category_id = 900 + len(self.created_categories) * 7
        created = _api(self.router, 'POST', '/api/v1/catalog/categories',
                       {'category_id': str(category_id), 'name': 'Тестовая категория'}, authorization=token)
        self.assertEqual(201, created.status)
        self.created_categories.append(category_id)
        updated = _api(self.router, 'PUT', f'/api/v1/catalog/categories/{category_id}',
                       {'name': 'Категория 2'}, authorization=token)
        self.assertEqual('Категория 2', updated.data['name'])
        # Entry with a missing category must be rejected with 404.
        with self.assertRaises(APIError) as ctx:
            _api(self.router, 'POST', '/api/v1/catalog/entries',
                 {'entry_id': f'E{self.suffix}', 'category_id': '99999', 'title': 'x'}, authorization=token)
        self.assertEqual(404, ctx.exception.status)

    def test_entries_and_links_crud(self):
        token = self._admin_token()
        category_id = 900 + len(self.created_categories) * 7
        _api(self.router, 'POST', '/api/v1/catalog/categories',
             {'category_id': str(category_id), 'name': 'Кат для записей'}, authorization=token)
        self.created_categories.append(category_id)
        entry_id = f'E{self.suffix}'
        entry = _api(self.router, 'POST', '/api/v1/catalog/entries',
                     {'entry_id': entry_id, 'category_id': str(category_id),
                      'title': 'Запись теста', 'sign1': 'признак'}, authorization=token)
        self.assertEqual(201, entry.status)
        self.created_entries.append(entry_id)
        self.assertEqual('признак', entry.data['sign1'])
        filtered = _api(self.router, 'GET', f'/api/v1/catalog/entries?category_id={category_id}', authorization=token)
        self.assertIn(entry_id, [row['id'] for row in filtered.data])
        link = _api(self.router, 'POST', '/api/v1/catalog/entry-services',
                    {'entry_id': entry_id, 'service_code': '101',
                     'condition_text': 'условие', 'value': 'значение'}, authorization=token)
        self.assertEqual(201, link.status)
        link_id = link.data['id']
        self.created_links.append(link_id)
        self.assertTrue(link.data['is_main'] is False or link.data['is_main'] is True)
        updated_link = _api(self.router, 'PUT', f'/api/v1/catalog/entry-services/{link_id}',
                            {'value': 'новое значение'}, authorization=token)
        self.assertEqual('новое значение', updated_link.data['value'])
        # Deleting the entry cascades to its links.
        _api(self.router, 'DELETE', f'/api/v1/catalog/entries/{entry_id}', {}, authorization=token)
        self.created_entries.remove(entry_id)
        listing = _api(self.router, 'GET', f'/api/v1/catalog/entry-services?entry_id={entry_id}', authorization=token)
        self.assertEqual([], listing.data)

    def test_deleting_referenced_service_is_blocked(self):
        token = self._admin_token()
        with self.assertRaises(APIError) as ctx:
            _api(self.router, 'DELETE', '/api/v1/catalog/services/101', {}, authorization=token)
        self.assertEqual(409, ctx.exception.status)

    def test_geo_address_crud(self):
        token = self._admin_token()
        address_id = f'addr-{self.suffix}'
        created = _api(self.router, 'POST', '/api/v1/catalog/geo-addresses',
                       {'address_id': address_id, 'street': 'Ленина', 'house': '10',
                        'lat': 56.2, 'lon': 93.5}, authorization=token)
        self.assertEqual(201, created.status)
        self.created_addresses.append(address_id)
        self.assertEqual('Ленина', created.data['street'])
        updated = _api(self.router, 'PUT', f'/api/v1/catalog/geo-addresses/{address_id}',
                       {'house': '12'}, authorization=token)
        self.assertEqual('12', updated.data['house'])
        found = _api(self.router, 'GET', '/api/v1/catalog/geo-addresses?kind=building', authorization=token)
        self.assertIn(address_id, [row['id'] for row in found.data])


if __name__ == '__main__':
    unittest.main()