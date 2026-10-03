"""Private photo surveys, persistent processing checkpoints and model revisions."""
import base64
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid
import warnings

from flask import Blueprint, abort, jsonify, request, send_file
from PIL import Image, ImageOps, UnidentifiedImageError

from photo_model import MODEL_INSTRUCTIONS, REVISION_SCHEMA, validate_revision

Image.MAX_IMAGE_PIXELS = 40_000_000
MAX_PHOTOS = 120
BATCH_SIZE = 8
MODEL = 'gpt-6-astra'
ZONES = ['front', 'rear', 'left', 'right', 'garden', 'driveway', 'other']


def uid():
    return uuid.uuid4().hex


def encode(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False)


class PhotoStore:
    def __init__(self, root):
        self.root = Path(root) / 'surveys'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.files = self.root / 'images'
        self.files.mkdir(exist_ok=True, mode=0o700)
        self.path = self.root / 'photos.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS surveys(id TEXT PRIMARY KEY, name TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY, survey TEXT, hash TEXT,
                    zone TEXT, note TEXT, created REAL, bytes INTEGER, UNIQUE(survey,hash));
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, survey TEXT, state TEXT,
                    created REAL, updated REAL, photos TEXT, anchors TEXT, base_revision TEXT,
                    model TEXT, batches TEXT, inflight INTEGER DEFAULT 0, error TEXT DEFAULT '', revision TEXT);
                CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY, job TEXT, created REAL, data TEXT);
                CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, previous TEXT, current TEXT, created REAL);
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def active(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE name='active'").fetchone()
        return row['value'] if row else None

    def revision(self, revision_id):
        if not revision_id:
            return None
        with self.connect() as db:
            row = db.execute('SELECT * FROM revisions WHERE id=?', (revision_id,)).fetchone()
        if not row:
            raise ValueError('Revision not found.')
        return {'id': row['id'], 'job': row['job'], 'created': row['created'], 'data': json.loads(row['data'])}

    def surveys(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('''SELECT s.*, COUNT(p.id) AS photo_count FROM surveys s
                LEFT JOIN photos p ON s.id=p.survey GROUP BY s.id ORDER BY s.created DESC''')]

    def photos(self, survey):
        with self.connect() as db:
            if not db.execute('SELECT id FROM surveys WHERE id=?', (survey,)).fetchone():
                raise ValueError('Survey not found.')
            return [dict(row) for row in db.execute('SELECT id,zone,note,created,bytes FROM photos WHERE survey=? ORDER BY created,id', (survey,))]

    def add_photo(self, survey, stream, zone, note):
        if zone not in ZONES or not isinstance(note, str) or len(note) > 500:
            raise ValueError('Choose a valid area and keep notes under 500 characters.')
        raw = stream.read(20 * 1024 * 1024 + 1)
        if not raw or len(raw) > 20 * 1024 * 1024:
            raise ValueError('Each photo must be below 20 MB.')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as original:
                    if original.format not in {'JPEG', 'PNG', 'WEBP'}:
                        raise ValueError('Use JPEG, PNG or WebP. Export HEIC photos as JPEG first.')
                    original.load()
                    photo = ImageOps.exif_transpose(original).convert('RGB')
                    if min(photo.size) < 128:
                        raise ValueError('Photo resolution is too small; use at least 128 pixels each way.')
                    photo.thumbnail((2400, 2400))
                    output = BytesIO()
                    photo.save(output, 'JPEG', quality=90, optimize=True)
                    data = output.getvalue()  # Re-encoding strips EXIF/GPS and other metadata.
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise ValueError('This file could not be safely decoded as a photo.') from error
        digest = hashlib.sha256(data).hexdigest()
        photo_id = uid()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT id FROM surveys WHERE id=?', (survey,)).fetchone():
                raise ValueError('Survey not found.')
            previous = db.execute('SELECT id FROM photos WHERE survey=? AND hash=?', (survey, digest)).fetchone()
            if previous:
                return previous['id'], True
            count = db.execute('SELECT COUNT(*) FROM photos WHERE survey=?', (survey,)).fetchone()[0]
            if count >= MAX_PHOTOS:
                raise ValueError('This survey has 120 photos. Start another survey to add more.')
            total = db.execute('SELECT COALESCE(SUM(bytes),0) FROM photos').fetchone()[0]
            if total + len(data) > 4 * 1024 ** 3:
                raise ValueError('Photo storage is full. Ask the site administrator to archive older surveys.')
            path = self.files / (photo_id + '.jpg')
            try:
                with path.open('xb') as file:
                    file.write(data)
                path.chmod(0o600)
                db.execute('INSERT INTO photos VALUES (?,?,?,?,?,?,?)', (photo_id, survey, digest, zone, note.strip(), time.time(), len(data)))
                db.commit()
            except Exception:
                path.unlink(missing_ok=True)
                raise
        return photo_id, False

    def jobs(self, survey=None):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM jobs' + (' WHERE survey=?' if survey else '') + ' ORDER BY created DESC LIMIT 30', (survey,) if survey else ())
            result = []
            for row in rows:
                item = dict(row)
                item['photo_count'] = len(json.loads(item.pop('photos')))
                item['completed_batches'] = len(json.loads(item.pop('batches')))
                item['total_batches'] = (item['photo_count'] + BATCH_SIZE - 1) // BATCH_SIZE
                item.pop('anchors')
                result.append(item)
            return result

    def enqueue(self, survey, anchors, model):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT id FROM jobs WHERE state IN ('queued','running')").fetchone():
                raise ValueError('A photo job is already in progress. Wait for it to finish first.')
            photos = [dict(row) for row in db.execute('SELECT id,zone,note FROM photos WHERE survey=? ORDER BY created,id', (survey,))]
            if not photos:
                raise ValueError('Upload at least one photo first.')
            job_id, now = uid(), time.time()
            db.execute('INSERT INTO jobs(id,survey,state,created,updated,photos,anchors,base_revision,model,batches) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (job_id, survey, 'queued', now, now, encode(photos), encode(anchors), self.active(), model, '[]'))
        return job_id

    def apply(self, revision_id, expected):
        self.revision(revision_id)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM settings WHERE name='active'").fetchone()
            previous = row['value'] if row else None
            if previous != expected:
                raise ValueError('The active revision changed. Refresh before applying this preview.')
            db.execute('INSERT INTO history(previous,current,created) VALUES(?,?,?)', (previous, revision_id, time.time()))
            db.execute("INSERT OR REPLACE INTO settings VALUES('active',?)", (revision_id,))

    def undo(self, expected):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM settings WHERE name='active'").fetchone()
            if (row['value'] if row else None) != expected:
                raise ValueError('The active revision changed. Refresh before undoing.')
            last = db.execute('SELECT * FROM history ORDER BY id DESC LIMIT 1').fetchone()
            if not last:
                raise ValueError('There is no applied change to undo.')
            db.execute("INSERT OR REPLACE INTO settings VALUES('active',?)", (last['previous'],))
            db.execute('DELETE FROM history WHERE id=?', (last['id'],))


class OpenAIModel:
    def __init__(self, environment=None):
        self.environment = os.environ if environment is None else environment
        self.model = self.environment.get('HOUSE_OPENAI_MODEL') or self.environment.get('OPENAI_MODEL') or MODEL
        self.configured = bool(self.environment.get('OPENAI_API_KEY'))

    def analyse(self, context, images):
        if not self.configured:
            raise ValueError('OpenAI is not configured on the server.')
        content = [{'type': 'input_text', 'text': encode(context)}]
        for photo_id, data in images:
            content += [{'type': 'input_text', 'text': 'Photo ID: ' + photo_id},
                        {'type': 'input_image', 'image_url': 'data:image/jpeg;base64,' + base64.b64encode(data).decode(), 'detail': 'high'}]
        payload = {'model': self.model, 'store': False, 'reasoning': {'effort': 'high'},
                   'instructions': MODEL_INSTRUCTIONS, 'input': [{'role': 'user', 'content': content}],
                   'text': {'format': {'type': 'json_schema', 'name': 'house_revision', 'strict': True, 'schema': REVISION_SCHEMA}},
                   'max_output_tokens': 14000}
        headers = {'Authorization': 'Bearer ' + self.environment['OPENAI_API_KEY'], 'Content-Type': 'application/json'}
        for key, name in [('OPENAI_PROJECT', 'OpenAI-Project'), ('OPENAI_ORG_ID', 'OpenAI-Organization')]:
            if self.environment.get(key):
                headers[name] = self.environment[key]
        try:
            with urlopen(Request('https://api.openai.com/v1/responses', data=encode(payload).encode(), headers=headers, method='POST'), timeout=600) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ValueError('OpenAI returned an oversized result.')
                result = json.loads(raw)
        except HTTPError as error:
            raise ValueError({401: 'OpenAI rejected the server API key.', 403: 'This API project cannot use the selected model.',
                              429: 'OpenAI quota or rate limit reached. Check billing or retry later.'}.get(error.code,
                              f'OpenAI request failed (HTTP {error.code}). No model changes were applied.')) from None
        except (URLError, TimeoutError, OSError):
            raise ValueError('OpenAI connection interrupted. A request may have been charged; retry explicitly when ready.') from None
        if result.get('status') != 'completed':
            raise ValueError('OpenAI did not complete the result. No model changes were applied.')
        texts = [part['text'] for item in result.get('output', []) if item.get('type') == 'message'
                 for part in item.get('content', []) if part.get('type') == 'output_text']
        try:
            return json.loads(''.join(texts))
        except (TypeError, ValueError):
            raise ValueError('OpenAI returned an unusable model result.') from None


class PhotoWorker:
    def __init__(self, store, api):
        self.store, self.api = store, api
        self.wake = threading.Event()
        self.stop = threading.Event()

    def recover(self):
        with self.store.connect() as db:
            # A request interrupted by restart may already have cost money. Never silently repeat it.
            db.execute("UPDATE jobs SET state='failed',error=?,updated=? WHERE state='running'",
                       ('Server restarted during processing. Finished batches were saved. Retry resumes them; an interrupted request may be charged twice.', time.time()))

    def start(self):
        self.recover()
        thread = threading.Thread(target=self.run, name='house-photo-worker', daemon=True)
        thread.start()
        return thread

    def run(self):
        while not self.stop.is_set():
            if not self.process_one():
                self.wake.wait(10)
                self.wake.clear()

    def process_one(self):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return False
            job = dict(row)
            db.execute("UPDATE jobs SET state='running',updated=? WHERE id=?", (time.time(), job['id']))
        try:
            if job['model'] != self.api.model:
                raise ValueError('The server model changed. Start a new processing job to use the new model.')
            photos, anchors, batches = json.loads(job['photos']), json.loads(job['anchors']), json.loads(job['batches'])
            photo_ids = {p['id'] for p in photos}
            previous = self.store.revision(job['base_revision'])
            prior = previous['data'] if previous else None
            prior_ids = {p for f in (prior or {}).get('features', []) for p in f['evidence']}
            for index, start in enumerate(range(0, len(photos), BATCH_SIZE)):
                if index < len(batches):
                    continue
                group = photos[start:start + BATCH_SIZE]
                self.inflight(job['id'], True)
                result = self.api.analyse({'stage': 'Observe this batch only', 'anchors': anchors, 'photos': group},
                                          [(p['id'], (self.store.files / (p['id'] + '.jpg')).read_bytes()) for p in group])
                validate_revision(result, {p['id'] for p in group})
                batches.append(result)
                with self.store.connect() as db:
                    db.execute('UPDATE jobs SET batches=?,inflight=0,updated=? WHERE id=?', (encode(batches), time.time(), job['id']))
            self.inflight(job['id'], True)
            merged = self.api.analyse({'stage': 'Consolidate all batches into the complete photo-additions revision. Deduplicate objects and list uncertainty.',
                                       'anchors': anchors, 'photos': photos, 'batches': batches, 'previous_revision': prior}, [])
            validate_revision(merged, photo_ids | prior_ids)
            revision_id = uid()
            with self.store.connect() as db:
                db.execute('INSERT INTO revisions VALUES(?,?,?,?)', (revision_id, job['id'], time.time(), encode(merged)))
                db.execute("UPDATE jobs SET state='ready',inflight=0,revision=?,updated=? WHERE id=?", (revision_id, time.time(), job['id']))
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else 'Processing failed safely. Your uploaded photos and the current model were preserved.'
            with self.store.connect() as db:
                db.execute("UPDATE jobs SET state='failed',error=?,updated=? WHERE id=?", (message[:1000], time.time(), job['id']))
        return True

    def inflight(self, job_id, value):
        with self.store.connect() as db:
            db.execute('UPDATE jobs SET inflight=?,updated=? WHERE id=?', (int(value), time.time(), job_id))


def register_photos(app, root, get_project):
    store = PhotoStore(root)
    api = app.config.get('PHOTO_API') or OpenAIModel()
    worker = PhotoWorker(store, api)
    app.extensions['photos'] = store
    app.extensions['photo_worker'] = worker
    bp = Blueprint('photos', __name__)

    @bp.errorhandler(ValueError)
    def bad_input(error):
        return jsonify(error=str(error)), 400

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError('Expected a JSON object.')
        return value

    @bp.get('/api/photos/status')
    def status():
        with store.connect() as db:
            revisions = [dict(r) for r in db.execute('SELECT id,created,job FROM revisions ORDER BY created DESC LIMIT 50')]
        return jsonify(csrf=app.jinja_env.globals['csrf_token'](), configured=api.configured, model=api.model, surveys=store.surveys(), jobs=store.jobs(),
                       active=store.active(), revisions=revisions, max_photos=MAX_PHOTOS, batch_size=BATCH_SIZE)

    @bp.post('/api/surveys')
    def create_survey():
        name = body().get('name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError('Give the survey a name of 1–100 characters.')
        survey_id = uid()
        with store.connect() as db:
            if db.execute('SELECT COUNT(*) FROM surveys').fetchone()[0] >= 200:
                raise ValueError('Survey limit reached. Ask the site administrator to archive older surveys.')
            db.execute('INSERT INTO surveys VALUES(?,?,?)', (survey_id, name.strip(), time.time()))
        return jsonify(id=survey_id), 201

    @bp.get('/api/surveys/<survey_id>')
    def survey_detail(survey_id):
        return jsonify(photos=store.photos(survey_id), jobs=store.jobs(survey_id))

    @bp.post('/api/surveys/<survey_id>/photos')
    def upload(survey_id):
        files = request.files.getlist('photo')
        if len(files) != 1:
            raise ValueError('Upload one photo per request.')
        photo_id, duplicate = store.add_photo(survey_id, files[0].stream, request.form.get('zone', 'other'), request.form.get('note', ''))
        return jsonify(id=photo_id, duplicate=duplicate), 200 if duplicate else 201

    @bp.get('/api/photos/<photo_id>/image')
    def image(photo_id):
        with store.connect() as db:
            exists = db.execute('SELECT id FROM photos WHERE id=?', (photo_id,)).fetchone()
        if not exists:
            abort(404)
        path = store.files / (photo_id + '.jpg')
        if request.args.get('thumb') == '1':
            with Image.open(path) as photo:
                photo.thumbnail((320, 320))
                output = BytesIO()
                photo.save(output, 'JPEG', quality=75)
                output.seek(0)
            return send_file(output, mimetype='image/jpeg')
        return send_file(path, mimetype='image/jpeg')

    @bp.post('/api/surveys/<survey_id>/process')
    def process(survey_id):
        if not api.configured:
            return jsonify(error='The server needs an OpenAI API key before processing. Photo uploads are available.'), 503
        if body().get('consent') is not True:
            raise ValueError('Confirm sending the survey photos to OpenAI.')
        project = get_project()
        config = project['config']
        anchors = {'house_bounds': config.get('house_bounds'),
                   'plot_defaults': project.get('plot', {}).get('defaults'),
                   'floor_height_m': config.get('floor_height_m'),
                   'model_reports': {name: dict(model.get('report', {})) for name, model in project.get('models', {}).items()},
                   'notes': 'CAD scale is fixed. Site dimensions are approximate. Baseline includes driveway paving, planting, boundary fences and field hedge.'}
        # Only geometrical context leaves the server, not source paths, title or address.
        for report in anchors['model_reports'].values():
            report.pop('filename', None)
        job_id = store.enqueue(survey_id, anchors, api.model)
        worker.wake.set()
        return jsonify(id=job_id), 202

    @bp.post('/api/jobs/<job_id>/retry')
    def retry(job_id):
        if not api.configured:
            return jsonify(error='OpenAI is not configured.'), 503
        if body().get('consent') is not True:
            raise ValueError('Confirm retrying the OpenAI requests.')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT id FROM jobs WHERE state IN ('queued','running')").fetchone():
                raise ValueError('A photo job is already in progress.')
            row = db.execute('SELECT state,model FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row or row['state'] != 'failed' or row['model'] != api.model:
                raise ValueError('This job cannot be retried. Start a new processing job instead.')
            db.execute("UPDATE jobs SET state='queued',error='',inflight=0,updated=? WHERE id=?", (time.time(), job_id))
        worker.wake.set()
        return jsonify(ok=True), 202

    @bp.get('/api/revisions/<revision_id>')
    def revision(revision_id):
        return jsonify(store.revision(revision_id))

    @bp.post('/api/revisions/<revision_id>/apply')
    def apply_revision(revision_id):
        store.apply(revision_id, body().get('expected_active'))
        return jsonify(active=store.active())

    @bp.post('/api/revisions/undo')
    def undo_revision():
        store.undo(body().get('expected_active'))
        return jsonify(active=store.active())

    app.register_blueprint(bp)
    if app.config.get('PHOTO_WORKER_ENABLED', False):
        worker.start()
    return store
