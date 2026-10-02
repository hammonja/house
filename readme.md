# House Design

Python/Flask and Three.js house-design study app. Existing and proposed DXF models share simplified materials, editable site context and a photo-informed driveway.

## Private data

This is a public code repository. Never commit photographs, DXFs, generated models, survey metadata, credentials, databases, user uploads, private exports or the private data directory. Private project data lives under `HOUSE_DATA_DIR` (default `private/`), with `data/project.json`, `data/plot.json` and `source/` beneath it. The deployment owner transfers that package separately. Access must be protected before exposing the app publicly.

## Run locally

Install `requirements.txt`, supply the private data package, then run `python app.py`. The app binds to loopback on port 5055 (`HOUSE_PORT` can change the port). Set `HOUSE_LOCAL_HTTP=1` for local HTTP development only; production session cookies require HTTPS. The supplied deploy unit is a template, not proof of server configuration.

## PiDash deployment and first sign-in

Use the project’s `app.py` entry point. On Linux it prepares a project `.venv`, installs `requirements.txt` when its contents change, and serves with Waitress. It works when PiDash initially selects system Python. HTTPS is supplied by the local Cloudflare tunnel; do not expose the loopback service directly.

Place the private data archive at `house-private-seed.zip` beside the app directory, or set `HOUSE_SEED_ARCHIVE` to its location. On first startup it imports the data-only archive into `HOUSE_DATA_DIR` (default `private/`). It validates paths, file types and size limits, and never overwrites an existing private project. Invalid or missing data leaves the login/setup screen accessible; signed-in users see a setup message instead of a service crash.

The first startup creates `private/setup-code.txt`. Open that file through your authenticated PiDash Files page, then enter its one-time code and choose a password at `/setup`. The setup code is required to create the password and is removed afterward. No default password exists. Password hashes and persistent session secrets remain in `private/auth.json`, outside Git. Keep a private backup of this directory. Every model, report, reference image and drawing requires sign-in. Password forms use CSRF checks and bounded attempts; private responses are not cached.

Pull updates through PiDash’s Git page, then restart the house service and check `/health` for version `0.3.1`. Enable Start on boot after a successful startup. Do not change the tunnel route when updating the code.

## Current baseline

Version 0.3 imports DXF 3DFACEs, aligns floors, displays existing/proposed comparison and editable plot context, exports house-only GLBs and PNG snapshots, and shows local reference images. Some CAD surfaces may be missing; do not invent surveyed precision. Materials and vegetation intentionally stay simple.

The original source contained private house-specific constants; they now come from private project configuration (`house_bounds`, `floor_plates`, `source_files`, origin and floor registration). Private drawings and images are intentionally absent from this repository. Version 0.3.1 adds protected first-run setup and recoverable missing-data handling.

## Next release

See `IMPLEMENTATION.md` for the user-requested photo-capture PWA and OpenAI processing workflow, which is not part of this baseline release. Retain the login, protected asset routes and private configuration when implementing it.

## Tests

Run `python -m unittest discover -s tests -v`. The startup, access-control and private-import tests use synthetic data only.
