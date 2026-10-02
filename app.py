from io import BytesIO
import math
import os
import json
from flask import Flask, abort, jsonify, render_template, request, send_file, send_from_directory
from cad import ROOT, build_project, export_glb


def create_app():
    app = Flask(__name__)
    project = build_project()
    project['plot'] = json.loads((ROOT / 'data/plot.json').read_text(encoding='utf-8'))

    @app.get('/')
    def index():
        return render_template('index.html', project_title=project['config']['title'], plot_source_url=project['plot']['source_url'])

    @app.get('/health')
    def health():
        return jsonify(status='ok', app='house-design', version='0.3.0')

    @app.get('/api/project')
    def project_data():
        response = jsonify(project)
        response.headers['Cache-Control'] = 'no-cache'
        return response

    @app.get('/api/report')
    def report():
        return jsonify(config=project['config'], plot=project['plot'], elevations=project['elevations'],
                       models={s: m['report'] for s, m in project['models'].items()})

    @app.get('/models/<scheme>.glb')
    def download_model(scheme):
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
        allowed = {'front.png', 'rear.png', 'drive-overhead.png'} | {e['filename'] for e in project['elevations']} | {
            m['report']['filename'] for m in project['models'].values()}
        if name not in allowed:
            abort(404)
        return send_from_directory(ROOT / 'source', name, as_attachment=name.endswith('.dxf'))

    return app


app = create_app()
if __name__ == '__main__':
    app.run(host=os.environ.get('HOUSE_HOST', '127.0.0.1'), port=int(os.environ.get('HOUSE_PORT', '5055')), debug=False)
