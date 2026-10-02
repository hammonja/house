"""Conservative ASCII DXF 3DFACE importer and glTF 2.0 exporter.

This intentionally handles the mesh entities present in this project. It does
not pretend that arbitrary 2D DXFs or ACIS solids can be converted automatically.
Original coordinates, layers, handles and unsupported counts remain traceable.
"""
from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json
import math
import struct
import os

CODE_ROOT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("HOUSE_DATA_DIR", str(CODE_ROOT / "private"))).resolve()
CONFIG = {}
PALETTE = {
    "render": [0.83, 0.82, 0.75, 1], "interior": [0.92, 0.90, 0.84, 1],
    "roof": [0.36, 0.22, 0.15, 1], "frame": [0.92, 0.92, 0.86, 1],
    "glass": [0.24, 0.39, 0.41, 0.58], "door": [0.42, 0.53, 0.43, 1],
    "stairs": [0.58, 0.46, 0.31, 1], "trim": [0.85, 0.83, 0.76, 1],
}


def read_dxf(path):
    """Read records in ENTITIES only; never evaluate document content."""
    lines = path.read_text(encoding="cp1252").splitlines()
    if len(lines) % 2:
        raise ValueError(f"{path.name}: incomplete DXF group pair")
    pairs = [(int(lines[i].strip()), lines[i + 1].strip()) for i in range(0, len(lines), 2)]
    units = None
    for i, pair in enumerate(pairs[:-1]):
        if pair == (9, "$INSUNITS"):
            units = int(pairs[i + 1][1])
    section = None
    records = []
    record = None
    for i, (code, value) in enumerate(pairs):
        if code == 0:
            if record is not None:
                records.append(record)
                record = None
            if value == "SECTION":
                section = pairs[i + 1][1]
            elif value == "ENDSEC":
                section = None
            elif section == "ENTITIES":
                record = {0: value}
        elif record is not None:
            record[code] = value
    if record is not None:
        records.append(record)
    return records, units


def material_for(record):
    layer = record.get(8, "0")
    if layer == "Window":
        return "glass" if int(record.get(62, 256)) == 9 else "frame"
    return {"ExtWall": "render", "IntWall": "interior", "Roof": "roof",
            "Facia": "trim", "Window Sill": "trim", "Door Threshold": "trim",
            "Door": "door", "Stairs": "stairs"}.get(layer, "render")


def triangle_normal(a, b, c):
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    n = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
    size = math.sqrt(sum(x*x for x in n))
    return [x / size for x in n] if size > 1e-10 else None


def load_scheme(scheme):
    path = ROOT / "source" / CONFIG["source_files"][scheme]["plans"]
    records, units = read_dxf(path)
    if units != 4:
        raise ValueError("Project registration expects millimetres ($INSUNITS=4)")
    counts = Counter(r[0] for r in records)
    faces = []
    origin = CONFIG["origin_mm"]
    for rec in records:
        if rec[0] != "3DFACE":
            continue
        raw = [[float(rec.get(c + i, rec.get(c + 2, 0))) for c in (10, 20, 30)] for i in range(4)]
        if not all(math.isfinite(x) for v in raw for x in v):
            raise ValueError(f"Non-finite geometry at handle {rec.get(5)}")
        upper = sum(v[0] for v in raw) / 4 > CONFIG["layout_split_x_mm"]
        dx = CONFIG["upper_floor_x_offset_mm"] if upper else 0
        # CAD Z up -> glTF Y up. Rear of house points towards negative Z.
        vertices = [[round((x - dx - origin[0]) / 1000, 6), round(z / 1000, 6),
                     round(-(y - origin[1]) / 1000, 6)] for x, y, z in raw]
        floor = "first" if upper else "ground"
        signature = (floor, rec.get(8), tuple(sorted(tuple(round(x, 3) for x in v) for v in vertices)))
        faces.append({"layer": rec.get(8, "0"), "floor": floor, "vertices": vertices,
                      "material": material_for(rec), "handle": rec.get(5), "signature": signature})
    return faces, {"filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "entity_counts": dict(counts), "source_units": "millimetres", "faces": counts["3DFACE"],
                   "unsupported": {k: v for k, v in counts.items() if k != "3DFACE"}}


def build_project(data_root=None):
    global ROOT, CONFIG
    if data_root is not None:
        ROOT = Path(data_root).resolve()
    CONFIG = json.loads((ROOT / 'data/project.json').read_text(encoding='utf-8'))
    loaded = {s: load_scheme(s) for s in ("existing", "proposed")}
    models = {}
    for scheme, (faces, report) in loaded.items():
        other = loaded["proposed" if scheme == "existing" else "existing"][0]
        signatures = {f["signature"] for f in other}
        grouped = defaultdict(lambda: {"positions": [], "normals": [], "uvs": [], "handles": []})
        skipped = 0
        for face in faces:
            changed = face["signature"] not in signatures
            key = (face["floor"], face["layer"], face["material"], changed)
            group = grouped[key]
            vs = face["vertices"]
            used = False
            for ids in ((0, 1, 2), (0, 2, 3)):
                tri = [vs[i] for i in ids]
                normal = triangle_normal(*tri)
                if normal is None:
                    skipped += 1
                    continue
                axis = max(range(3), key=lambda i: abs(normal[i]))
                for v in tri:
                    group["positions"].extend(v)
                    group["normals"].extend(round(x, 6) for x in normal)
                    group["uvs"].extend([v[2], v[1]] if axis == 0 else ([v[0], v[2]] if axis == 1 else [v[0], v[1]]))
                used = True
            if used:
                group["handles"].append(face["handle"])
        meshes = []
        for (floor, layer, material, changed), geometry in grouped.items():
            if geometry["positions"]:
                meshes.append({"floor": floor, "layer": layer, "material": material,
                               "changed": changed, **geometry})
        report["degenerate_triangles_skipped"] = skipped
        report["triangles"] = sum(len(g["positions"]) // 9 for g in meshes)
        report["retained_faces"] = sum(len(g["handles"]) for g in meshes)
        report["degenerate_faces_skipped"] = report["faces"] - report["retained_faces"]
        report["changed_faces"] = sum(len(g["handles"]) for g in meshes if g["changed"])
        models[scheme] = {"meshes": meshes, "report": report}
    elevations = []
    for scheme in ("Existing", "Proposed"):
        p = ROOT / "source" / CONFIG["source_files"][scheme.lower()]["elevations"]
        records, _ = read_dxf(p)
        elevations.append({"filename": p.name, "entities": len(records), "status": "empty" if not records else "not imported"})
    return {"config": CONFIG, "models": models, "elevations": elevations}


def export_glb(model, scheme, floor_height=2.7):
    """Export imported surfaces only, preserving floor, layer and change metadata."""
    blob = bytearray()
    views, accessors, meshes, nodes = [], [], [], []

    def accessor(values, width, bounds=False):
        while len(blob) % 4:
            blob.append(0)
        offset = len(blob)
        blob.extend(struct.pack('<' + 'f' * len(values), *values))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(values)*4, "target": 34962})
        obj = {"bufferView": len(views)-1, "componentType": 5126, "count": len(values)//width,
               "type": {2: "VEC2", 3: "VEC3"}[width]}
        if bounds:
            obj.update(min=[min(values[i::width]) for i in range(width)], max=[max(values[i::width]) for i in range(width)])
        accessors.append(obj)
        return len(accessors)-1

    material_names = list(PALETTE)
    materials = [{"name": name, "doubleSided": True, "alphaMode": "BLEND" if name == "glass" else "OPAQUE",
                  "pbrMetallicRoughness": {"baseColorFactor": PALETTE[name], "metallicFactor": 0, "roughnessFactor": .82}} for name in material_names]
    for item in model["meshes"]:
        attributes = {"POSITION": accessor(item["positions"], 3, True), "NORMAL": accessor(item["normals"], 3),
                      "TEXCOORD_0": accessor(item["uvs"], 2)}
        name = f'{item["floor"]} / {item["layer"]} / {item["material"]}'
        meshes.append({"name": name, "primitives": [{"attributes": attributes, "material": material_names.index(item["material"])}]})
        nodes.append({"name": name, "mesh": len(meshes)-1, "translation": [0, floor_height if item["floor"] == "first" else 0, 0],
                      "extras": {"sourceLayer": item["layer"], "sourceHandles": item["handles"], "changed": item["changed"]}})
    doc = {"asset": {"version": "2.0", "generator": "House Design / direct DXF faces"},
           "scene": 0, "scenes": [{"name": f"{scheme.title()} house", "nodes": list(range(len(nodes)))}],
           "nodes": nodes, "meshes": meshes, "materials": materials, "buffers": [{"byteLength": len(blob)}],
           "bufferViews": views, "accessors": accessors,
           "extras": {"units": "metres", "floorToFloorMetres": floor_height, "provisionalFloorLevel": True,
                      "source": model["report"], "notes": CONFIG["notes"]}}
    js = json.dumps(doc, separators=(',', ':')).encode()
    js += b' ' * (-len(js) % 4)
    blob += b'\0' * (-len(blob) % 4)
    return struct.pack('<4sII', b'glTF', 2, 12+8+len(js)+8+len(blob)) + struct.pack('<I4s', len(js), b'JSON') + js + struct.pack('<I4s', len(blob), b'BIN\0') + blob
