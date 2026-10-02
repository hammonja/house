"""Rebuild portable GLBs and an audit report from the original source DXFs."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cad import ROOT, build_project, export_glb

project=build_project()
output=ROOT/'exports'
output.mkdir(exist_ok=True)
for scheme, model in project['models'].items():
    path=output/f'house-{scheme}.glb'
    path.write_bytes(export_glb(model,scheme,project['config']['floor_height_m']))
    print(f'{path.name}: {model["report"]["retained_faces"]} faces, {model["report"]["triangles"]} triangles')
report={'config':project['config'],'elevations':project['elevations'],
        'plot':json.loads((ROOT/'data/plot.json').read_text(encoding='utf-8')),
        'models':{s:m['report'] for s,m in project['models'].items()}}
(output/'import-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
