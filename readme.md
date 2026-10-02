# House Design

Python/Flask and Three.js house-design study app. Existing and proposed DXF models share simplified materials, editable site context and a photo-informed driveway.

## Private data

This is a public code repository. Never commit photographs, DXFs, generated models, survey metadata, credentials, databases, user uploads, private exports or the private data directory. Private project data lives under `HOUSE_DATA_DIR` (default `private/`), with `data/project.json`, `data/plot.json` and `source/` beneath it. The deployment owner transfers that package separately. Access must be protected before exposing the app publicly.

## Run baseline locally

Install `requirements.txt`, supply the private data package, then run `python app.py`. The local baseline is port 5055. `HOUSE_PORT` and `HOUSE_HOST` configure binding. The supplied deploy unit is a template, not proof of server configuration.

## Current baseline

Version 0.3 imports DXF 3DFACEs, aligns floors, displays existing/proposed comparison and editable plot context, exports house-only GLBs and PNG snapshots, and shows local reference images. Some CAD surfaces may be missing; do not invent surveyed precision. Materials and vegetation intentionally stay simple.

The original source contained private house-specific constants; they now come from private project configuration (`house_bounds`, `floor_plates`, `source_files`, origin and floor registration). Private drawings and images are intentionally absent from this repository. The app needs a first-run/setup state before deployment without them.

## Next release

See `IMPLEMENTATION.md` for the user-requested photo-capture PWA and OpenAI processing workflow. Do not publicly deploy until login, protected asset routes and safe server-side key storage are complete.
