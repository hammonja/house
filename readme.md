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

Pull updates through PiDash’s Git page, then restart the house service and check `/health` for version `0.4.0`. Enable Start on boot after a successful startup. Do not change the tunnel route when updating the code.

## Current baseline

Version 0.3 imports DXF 3DFACEs, aligns floors, displays existing/proposed comparison and editable plot context, exports house-only GLBs and PNG snapshots, and shows local reference images. Some CAD surfaces may be missing; do not invent surveyed precision. Materials and vegetation intentionally stay simple.

The original source contained private house-specific constants; they now come from private project configuration (`house_bounds`, `floor_plates`, `source_files`, origin and floor registration). Private drawings and images are intentionally absent from this repository. Version 0.3.1 adds protected first-run setup and recoverable missing-data handling.

## Photo surveys (0.4.0)

Open **Photo surveys** from the viewer. Create a survey, label the part of the property, then use **Take photo** or select multiple files with **Upload photos**. The phone capture control requests the rear camera and falls back to the browser's file picker. Use overlapping daylight views with measured dimensions in the notes. JPEG, PNG and WebP are accepted, up to 20 MB each and 120 photos per survey; HEIC must be exported as JPEG. Images are decoded, oriented, resized to a maximum 2400 pixels and re-encoded without EXIF/GPS metadata. Identical normalized images in a survey are skipped.

The app is installable through the browser or iPhone's **Share → Add to Home Screen**. Open the photo page online once before taking it offline. Only public shell assets are cached by the service worker. Photos captured without a connection are explicit IndexedDB drafts on that device; choose the destination survey and press **Upload drafts** after reconnecting. Successfully synced drafts are removed from device storage. Keep device drafts until upload is confirmed; clearing browser storage loses unsynced photos. Authenticated model/photo/API responses are never cached by the service worker.

**Process photos** deliberately sends every photo present at that moment, its labels/notes and geometrical model anchors to OpenAI. The server uses the Responses API with strict structured output, high reasoning effort and `store=false`. The default model is `gpt-6-astra`; there is no automatic downgrade. Eight-image batches are followed by a consolidation pass which deduplicates observations and preserves prior photo additions where supported. Costs are billed to the configured OpenAI project. The screen shows the planned request count and requires explicit consent. This is photo-assisted modelling, not calibrated photogrammetry or survey measurement.

Credentials stay server-side: process environment first, project `.env` next, then missing `OPENAI_API_KEY`, `OPENAI_PROJECT` and `OPENAI_ORG_ID` fields from `../tools/.env`, matching Golf's shared configuration. `OPENAI_ENV_FILE` can point to a different file. Shared model settings are deliberately ignored; `HOUSE_OPENAI_MODEL` (or a project-local/environment `OPENAI_MODEL`) overrides House's model. `.env` is parsed as assignments without executing or interpolating it. No API key is returned to the browser or logged. A missing key permits uploads and disables processing.

One worker thread runs alongside Waitress under the `python app.py` entry point. Its SQLite job queue, photos, checkpoints and revisions live under `HOUSE_DATA_DIR/surveys/`, outside Git, and survive closing the browser and code redeployment. Completed batches are saved individually. A server restart marks an interrupted running job failed for explicit retry, retaining completed batches; an ambiguous interrupted API call can be billed again if retried. Queued work resumes automatically. Do not launch multiple app/worker processes against the same data directory. If using a custom WSGI launcher, explicitly start the single worker in that process or use `PHOTO_WORKER_ENABLED=True` in `create_app` configuration.

Review the summary, confidence and uncertainties, then **Preview in 3D** before **Apply this revision**. **Undo** restores the preceding applied revision. Photo additions use constrained trees, hedges, fences, paving, small box structures and gable prisms in metre coordinates with bounded dimensions and exact source-photo IDs. No model-generated code, arbitrary URLs or textures are executed. Additions appear on the existing-house view only; source CAD, scale and the proposal are preserved. They are estimates and may need better photos or measurements. Current GLB exports remain CAD-only; viewer snapshots include photo additions. Project-wide photo storage is capped at 4 GiB and 200 surveys; private archival/backup is an administrator operation.

## Tests

Run `python -m unittest discover -s tests -v` and `node tests/test_photo_scene.mjs`. Tests use synthetic images and mocked OpenAI responses: upload validation/metadata stripping/deduplication, auth/CSRF, complete batch coverage, recovery and explicit retry, schema/provenance rejection, preview/apply/undo, unchanged CAD/proposal, credential precedence, API request shape and actual low-poly geometry. Browser checks cover upload, offline drafts, preview/apply/undo and a narrow screen layout. Actual phone camera and installation require testing on a phone.
