"""Synthetic images and mock responses only; never send test calls to OpenAI."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from app import create_app
from photo_model import validate_revision
from photos import OpenAIModel, PhotoStore, PhotoWorker


def photo(number=1):
    stream = BytesIO()
    image = Image.new('RGB', (256, 192), (number % 255, 120, 70))
    exif = Image.Exif()
    exif[270] = 'Synthetic metadata must be stripped'
    image.save(stream, 'JPEG', exif=exif)
    stream.seek(0)
    return stream


def result(photo_id):
    return {'summary': 'Synthetic tree by the garden.', 'uncertainties': ['Height is estimated.'],
            'features': [{'label': 'Garden tree', 'kind': 'tree', 'position': [3, 0, -5], 'size': [2, 4, 2],
                          'rotation': 0, 'color': '#758760', 'confidence': 'medium', 'evidence': [photo_id],
                          'reason': 'Visible beside a known wall.'}]}


class MockAPI:
    configured = True
    model = 'gpt-6-astra'

    def __init__(self):
        self.calls = []
        self.fail_at = None

    def analyse(self, context, images):
        self.calls.append((context, images))
        if len(self.calls) == self.fail_at:
            raise ValueError('Synthetic interrupted request.')
        if images:
            return result(images[0][0])
        combined = deepcopy(context['batches'][0])
        combined['features'] = [feature for batch in context['batches'] for feature in batch['features']]
        return combined


class PhotoWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.api = MockAPI()
        self.fixture = {'config': {'title': 'Synthetic house', 'floor_height_m': 2.7,
                                  'house_bounds': {'left': -4, 'right': 4, 'front': 4, 'rear': -6}},
                        'plot': {'source_url': '', 'defaults': {'width': 12, 'depth': 40, 'setback': 6, 'leftGap': 2}},
                        'models': {'existing': {'report': {'filename': 'private.dxf', 'faces': 20}},
                                   'proposed': {'report': {'filename': 'proposal.dxf', 'faces': 22}}}, 'elevations': []}
        self.app = create_app({'TESTING': True, 'DATA_DIR': str(self.root), 'SEED_ARCHIVE': str(self.root/'none.zip'),
                               'PHOTO_API': self.api}, lambda: self.fixture)
        self.store = self.app.extensions['photos']
        self.worker = self.app.extensions['photo_worker']
        self.client = self.app.test_client()
        with self.client.session_transaction(base_url='https://localhost') as session:
            session['signed_in'] = True
            session['csrf'] = 'synthetic-csrf'
        self.survey = self.post('/api/surveys', {'name': 'Synthetic walk'}).json['id']

    def tearDown(self):
        self.temp.cleanup()

    def get(self, path):
        return self.client.get(path, base_url='https://localhost')

    def post(self, path, data):
        return self.client.post(path, json=data, base_url='https://localhost',
                                headers={'X-CSRF-Token': 'synthetic-csrf', 'Origin': 'https://localhost'})

    def upload(self, number=1):
        return self.client.post(f'/api/surveys/{self.survey}/photos', base_url='https://localhost',
                                data={'photo': (photo(number), '../../photo.jpg'), 'zone': 'garden'},
                                headers={'X-CSRF-Token': 'synthetic-csrf', 'Origin': 'https://localhost'})

    def job(self):
        return self.post(f'/api/surveys/{self.survey}/process', {'consent': True})

    def test_upload_is_validated_private_deduplicated_and_metadata_stripped(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        self.assertTrue(self.upload().json['duplicate'])
        self.assertEqual(len(self.store.photos(self.survey)), 1)
        path = self.store.files / (response.json['id'] + '.jpg')
        with Image.open(path) as image:
            self.assertFalse(image.getexif())
        self.assertFalse((self.root / 'photo.jpg').exists())
        retrieved = self.get('/api/photos/' + response.json['id'] + '/image?thumb=1')
        self.assertEqual(retrieved.status_code, 200)
        self.assertEqual(retrieved.headers['Cache-Control'], 'no-store')
        retrieved.close()
        invalid = self.client.post(f'/api/surveys/{self.survey}/photos', base_url='https://localhost',
                                   data={'photo': (BytesIO(b'<script>bad</script>'), 'fake.png')},
                                   headers={'X-CSRF-Token': 'synthetic-csrf'})
        self.assertEqual(invalid.status_code, 400)

    def test_every_photo_batched_then_revision_preview_apply_undo(self):
        baseline = deepcopy(self.fixture)
        ids = {self.upload(i*17).json['id'] for i in range(9)}
        response = self.job()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.job().status_code, 400)
        self.assertTrue(self.worker.process_one())
        self.assertEqual(len(self.api.calls), 3)
        self.assertEqual({photo_id for _, images in self.api.calls for photo_id, _ in images}, ids)
        job = self.store.jobs()[0]
        self.assertEqual(job['state'], 'ready')
        self.assertEqual(job['completed_batches'], 2)
        self.assertIsNone(self.store.active())
        revision = self.get('/api/revisions/' + job['revision']).json
        self.assertEqual(len(revision['data']['features']), 2)
        applied = self.post('/api/revisions/' + revision['id'] + '/apply', {'expected_active': None})
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(PhotoStore(self.root).active(), revision['id'])
        self.assertEqual(self.post('/api/revisions/undo', {'expected_active': 'stale'}).status_code, 400)
        self.assertEqual(self.post('/api/revisions/undo', {'expected_active': revision['id']}).status_code, 200)
        self.assertIsNone(self.store.active())
        self.assertEqual(self.fixture, baseline)

    def test_failed_batch_retry_preserves_finished_work(self):
        for i in range(9):
            self.upload(i*19)
        self.api.fail_at = 2
        self.job()
        self.worker.process_one()
        job = self.store.jobs()[0]
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(job['completed_batches'], 1)
        first_ids = {p for p, _ in self.api.calls[0][1]}
        self.api.fail_at = None
        self.assertEqual(self.post('/api/jobs/'+job['id']+'/retry', {'consent': True}).status_code, 202)
        self.worker.process_one()
        self.assertEqual(self.store.jobs()[0]['state'], 'ready')
        self.assertFalse(first_ids.intersection({p for _, images in self.api.calls[2:] for p, _ in images}))

    def test_restart_does_not_silently_repeat_an_inflight_paid_request(self):
        self.upload()
        self.job()
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET state='running',inflight=1")
        PhotoWorker(self.store, self.api).recover()
        self.assertEqual(self.store.jobs()[0]['state'], 'failed')
        self.assertIn('charged twice', self.store.jobs()[0]['error'])
        self.assertFalse(self.worker.process_one())
        self.assertEqual(self.api.calls, [])

    def test_missing_key_capture_works_but_process_does_not_charge(self):
        self.api.configured = False
        self.assertEqual(self.upload().status_code, 201)
        self.assertEqual(self.job().status_code, 503)
        self.assertEqual(self.api.calls, [])

    def test_consent_auth_and_csrf_are_required(self):
        self.upload()
        self.assertEqual(self.post(f'/api/surveys/{self.survey}/process', {}).status_code, 400)
        self.assertEqual(self.client.post('/api/surveys', json={'name': 'bad'}).status_code, 400)
        anonymous = self.app.test_client()
        for path in ['/api/photos/status', f'/api/surveys/{self.survey}', '/api/revisions/missing']:
            response = anonymous.get(path, base_url='https://localhost')
            self.assertEqual(response.status_code, 401)
            self.assertNotIn(b'Synthetic walk', response.data)
        for path in ['/manifest.webmanifest', '/sw.js']:
            with anonymous.get(path) as response:
                self.assertEqual(response.status_code, 200)

    def test_invalid_geometry_and_invented_provenance_rejected(self):
        item = result('known')
        self.assertEqual(validate_revision(item, {'known'}), item)
        for field, value in [('position', [float('nan'),0,0]), ('size', [1,-3,1]), ('rotation', float('inf')),
                              ('kind','javascript'), ('color','url(bad)'), ('evidence',['invented'])]:
            invalid = deepcopy(item)
            invalid['features'][0][field] = value
            with self.assertRaises(ValueError):
                validate_revision(invalid, {'known'})
        invalid = deepcopy(item)
        invalid['features'][0]['code'] = 'never execute'
        with self.assertRaises(ValueError):
            validate_revision(invalid, {'known'})

    def test_dangerous_model_response_cannot_create_revision(self):
        self.upload()
        self.job()
        self.api.analyse = lambda *args: {'code': 'do something'}
        self.worker.process_one()
        self.assertEqual(self.store.jobs()[0]['state'], 'failed')
        self.assertIsNone(self.store.active())
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0], 0)


class APIContractTests(unittest.TestCase):
    def test_responses_uses_images_strict_schema_and_server_only_credentials(self):
        api = OpenAIModel({'OPENAI_API_KEY': 'synthetic-secret'})
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, count): return json.dumps({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(result('photo'))}]}]}).encode()
        with patch('photos.urlopen', return_value=Response()) as call:
            self.assertEqual(api.analyse({'test':True}, [('photo', b'synthetic-image')]), result('photo'))
        request = call.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')
        self.assertEqual(payload['model'], 'gpt-6-astra')
        self.assertFalse(payload['store'])
        self.assertTrue(payload['text']['format']['strict'])
        self.assertEqual(payload['input'][0]['content'][2]['type'], 'input_image')
        self.assertNotIn('synthetic-secret', request.data.decode())


if __name__ == '__main__':
    unittest.main()
