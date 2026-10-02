"""Synthetic fixtures only: no private house data or credentials in this suite."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from app import create_app
from bootstrap import restore_seed


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'private'
        self.config = dict(TESTING=True, DATA_DIR=str(self.root), SEED_ARCHIVE=str(self.root / 'absent.zip'))
        self.fixture = {'config': {'title': 'Private synthetic house', 'floor_height_m': 2.7},
                        'plot': {'source_url': ''}, 'models': {}, 'elevations': []}
        self.app = create_app(self.config, lambda: self.fixture)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def post(self, path, data=None):
        self.client.get('/setup', base_url='https://localhost', follow_redirects=True)
        with self.client.session_transaction(base_url='https://localhost') as session:
            csrf = session.get('csrf')
        return self.client.post(path, base_url='https://localhost',
                                data={'csrf': csrf, **(data or {})}, headers={'Origin': 'https://localhost'})

    def setup_password(self):
        return self.post('/setup', {'setup_code': (self.root / 'setup-code.txt').read_text(),
                                    'password': 'synthetic-test-password', 'confirmation': 'synthetic-test-password'})

    def test_all_private_endpoints_require_login(self):
        for path in ['/api/project', '/api/report', '/models/existing.glb', '/reference/front.png', '/private/auth.json']:
            response = self.client.get(path, base_url='https://localhost')
            self.assertIn(response.status_code, (302, 401))
            self.assertNotIn(b'Private synthetic', response.data)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.get('/health').status_code, 200)

    def test_setup_needs_code_csrf_and_matching_passwords(self):
        self.assertEqual(self.client.post('/setup').status_code, 400)
        self.assertEqual(self.post('/setup', {'setup_code': 'wrong'}).status_code, 401)
        response = self.setup_password()
        self.assertEqual(response.status_code, 302)
        self.assertFalse((self.root / 'setup-code.txt').exists())
        stored = json.loads((self.root / 'auth.json').read_text())
        self.assertNotIn('synthetic-test-password', json.dumps(stored))
        self.assertEqual(self.client.get('/api/project', base_url='https://localhost').json, self.fixture)
        self.assertEqual(self.client.get('/setup', base_url='https://localhost').status_code, 302)

    def test_password_survives_restart_and_logout_revokes_access(self):
        self.setup_password()
        secret = self.app.secret_key
        self.app = create_app(self.config, lambda: self.fixture)
        self.assertEqual(self.app.secret_key, secret)
        self.client = self.app.test_client()
        self.assertEqual(self.post('/login', {'password': 'incorrect'}).status_code, 401)
        self.assertEqual(self.post('/login', {'password': 'synthetic-test-password'}).status_code, 302)
        self.client.get('/', base_url='https://localhost')
        self.assertEqual(self.post('/logout').status_code, 302)
        self.assertEqual(self.client.get('/api/project', base_url='https://localhost').status_code, 401)

    def test_cross_origin_rejected_and_cookies_secure(self):
        response = self.client.get('/setup', base_url='https://localhost')
        self.assertIn('Secure;', response.headers['Set-Cookie'])
        self.assertIn('HttpOnly;', response.headers['Set-Cookie'])
        with self.client.session_transaction(base_url='https://localhost') as session:
            token = session['csrf']
        response = self.client.post('/setup', base_url='https://localhost',
                                    data={'csrf': token}, headers={'Origin': 'https://evil.example'})
        self.assertEqual(response.status_code, 403)

    def test_missing_data_is_recoverable_without_startup_crash(self):
        app = create_app(self.config)
        client = app.test_client()
        self.assertEqual(client.get('/health').status_code, 200)
        with client.session_transaction(base_url='https://localhost') as session:
            session['signed_in'] = True
        self.assertEqual(client.get('/api/project', base_url='https://localhost').status_code, 503)
        self.assertEqual(client.get('/', base_url='https://localhost').status_code, 503)

    def test_login_attempts_are_bounded(self):
        for _ in range(10):
            self.post('/setup', {'setup_code': 'wrong'})
        self.assertEqual(self.post('/setup', {'setup_code': 'wrong'}).status_code, 429)


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.archive, self.target = self.base / 'seed.zip', self.base / 'private'

    def tearDown(self):
        self.temp.cleanup()

    def archive_files(self, extras=None):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name, value in {'data/project.json': '{}', 'data/plot.json': '{}', 'source/test.dxf': 'test', **(extras or {})}.items():
                info = zipfile.ZipInfo()
                info.filename = name  # Preserve hostile separators on Windows too.
                archive.writestr(info, value)

    def test_seed_installs_once_and_preserves_changes(self):
        self.archive_files()
        self.assertTrue(restore_seed(self.archive, self.target))
        (self.target / 'data/project.json').write_text('{"preserve":true}')
        self.assertFalse(restore_seed(self.archive, self.target))
        self.assertEqual(json.loads((self.target / 'data/project.json').read_text()), {'preserve': True})

    def test_traversal_and_code_files_are_rejected_atomically(self):
        for bad in ['../escape.txt', '/absolute.txt', 'source/../../escape.txt', 'source/code.py', 'data/auth.json', 'source\\bad.png']:
            self.archive_files({bad: 'test'})
            with self.assertRaises(ValueError):
                restore_seed(self.archive, self.target)
            self.assertFalse(self.target.exists())
            self.assertFalse((self.base / 'escape.txt').exists())

    def test_existing_partial_private_data_is_not_overwritten(self):
        self.archive_files()
        self.target.mkdir()
        (self.target / 'keep.txt').write_text('keep')
        with self.assertRaises(ValueError):
            restore_seed(self.archive, self.target)
        self.assertEqual((self.target / 'keep.txt').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
