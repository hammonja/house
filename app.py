from bootstrap import CODE_ROOT, prepare_runtime, restore_seed

if __name__ == '__main__':
    prepare_runtime()

from io import BytesIO
from pathlib import Path
import math
import os
import json
import threading
import zipfile
from flask import Flask, abort, jsonify, render_template, request, send_file, send_from_directory
from access import protect
from werkzeug.middleware.proxy_fix import ProxyFix


def create_app(config=None, project_loader=None):
    app = Flask(__name__)
    app.config.update(DATA_DIR=os.environ.get('HOUSE_DATA_DIR', str(CODE_ROOT / 'private')),
                      SEED_ARCHIVE=os.environ.get('HOUSE_SEED_ARCHIVE', str(CODE_ROOT.parent / 'house-private-seed.zip')),
                      SESSION_COOKIE_SECURE=os.environ.get('HOUSE_LOCAL_HTTP') != '1',
                      MAX_CONTENT_LENGTH=16 * 1024)
    if config:
        app.config.update(config)
    root = Path(app.config['DATA_DIR']).resolve()
    try:
        restore_seed(app.config['SEED_ARCHIVE'], root)
    except (ValueError, OSError, zipfile.BadZipFile):
        app.logger.error('Private data import needs administrator attention; existing files were preserved.')
    protect(app, root)
    # The service binds loopback only, behind the local Cloudflare tunnel.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
    project = None
    project_lock = threading.Lock()

    def get_project():
        nonlocal project
        with project_lock:
            if project is None:
                try:
                    if project_loader:
                        candidate = project_loader()
                    else:
                        from cad import build_project
                        candidate = build_project(root)
                        candidate['plot'] = json.loads((root / 'data/plot.json').read_text(encoding='utf-8'))
                    project = candidate
                except (OSError, ValueError, KeyError):
                    app.logger.error('Private project files are missing or invalid.')
                    abort(503, 'The private project files need to be installed. Please check PiDash.')
        return project

    @app.errorhandler(503)
    def project_unavailable(error):
        if request.path.startswith('/api/'):
            return jsonify(error=error.description), 503
        return render_template('unavailable.html'), 503

    @app.get('/')
    def index():
        project = get_project()
        return render_template('index.html', project_title=project['config']['title'], plot_source_url=project['plot']['source_url'])

    @app.get('/health')
    def health():
        return jsonify(status='ok', app='house-design', version='0.3.1')

    @app.get('/api/project')
    def project_data():
        return jsonify(get_project())

    @app.get('/api/report')
    def report():
        project = get_project()
        return jsonify(config=project['config'], plot=project['plot'], elevations=project['elevations'],
                       models={s: m['report'] for s, m in project['models'].items()})

    @app.get('/models/<scheme>.glb')
    def download_model(scheme):
        project = get_project()
        from cad import export_glb
        if scheme not in project['models']:
            abort(404)
        try:
            height = float(request.args.get('floor_height', project['config']['floor_height_m']))
        except (ValueError, TypeError):
            abort(400, 'Invalid floor height')
        if not math.isfinite(height) or not 2.4 <= height <= 3.4:
            abort(400, 'Floor height must be between 2.40 and 3.40 m')
        data = export_glb(project['models'][scheme], scheme, height)
        return send_file(BytesIO(data), mimetype='model/gltf-binary', as_attachment=True,
                         download_name=f'house-{scheme}.glb')

    @app.get('/reference/<name>')
    def reference(name):
        project = get_project()
        allowed = {'front.png', 'rear.png', 'drive-overhead.png'} | {e['filename'] for e in project['elevations']} | {
            m['report']['filename'] for m in project['models'].values()}
        if name not in allowed:
            abort(404)
        return send_from_directory(root / 'source', name, as_attachment=name.endswith('.dxf'))

    return app


app = create_app()
if __name__ == '__main__':
    from waitress import serve
    serve(app, host='127.0.0.1', port=int(os.environ.get('HOUSE_PORT', '5055')),
          threads=4, trusted_proxy='127.0.0.1', trusted_proxy_headers={'x-forwarded-proto'},
          clear_untrusted_proxy_headers=True)
