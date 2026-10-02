# Photo modelling PWA release

The user requests implementation and release of this app through their existing PiDash at `https://dash.hammonja.com`, starting by adding the site on PiDash's Cloudflare page. The confirmed destination is `https://house.hammonja.com`, repository `hammonja/house`. The user explicitly wants development to continue in the cloud while the Windows computer is off.

## Product requirements

- Keep the existing Three.js visual character: simple geometry, restrained materials, low-poly trees. Do not switch to photorealistic image textures, NeRFs or splats.
- Installable mobile PWA with Take photo (rear camera) and multi-photo Upload buttons. Support walks around the property with overlapping photos from multiple angles. Include simple capture guidance, zone/direction labels, thumbnails, upload progress, duplicate handling and reliable error messages. Provide browser-file capture fallback. No background camera capture.
- A deliberate Process photos button starts server-side processing of the selected survey. Explain that those images are sent to OpenAI. Closing the phone/browser must not stop the job. Persist jobs, progress, batches, results and errors outside Git; allow revisiting status. Do not silently ignore images beyond a batch limit.
- Use OpenAI Responses API with `gpt-6-astra` (the documented most capable model as checked on 2026-10-02); high-quality reasoning, configurable server-side model, no silent downgrade. Keep the API key server-side in a protected environment/private config. No key in JS, service-worker cache, Git or logs. If no key is configured, show a clear configuration state and allow capture/uploads without paid calls. Never request credentials in a public issue/commit.
- Use image batches for detailed observations, then consolidate into validated model updates with source-photo provenance and confidence. Use the DXF model and known dimensions as anchors. Vision alone is not metric photogrammetry: do not claim recovered survey accuracy or fabricate hidden surfaces. Mark uncertain details and retain input dimension anchors. If users want metric reconstruction later, a separate calibrated multiview reconstruction stage is needed.
- Actually update the 3D scene, not just show an AI report. Use a constrained declarative schema for simplified geometry (e.g. trees, hedges, fencing, paving, roof/gable features, small structures and material/shape adjustments), validated finite numbers, bounded dimensions, polygon/mesh limits and supported types. Never execute model-generated Python, JS, shell, HTML or arbitrary URLs.
- Create saved model revisions; allow preview, apply and undo/revert. Preserve existing and proposed CAD geometry as the baseline. Survey photos describe existing features and must not silently replace the planner's proposal. Existing data/photos must survive redeploys.
- Keep desktop and mobile layouts practical, matching the existing app. Add a photo/survey workflow without cluttering the viewer. Update version and documentation.

## Private data and deployment

The repo is public. The user explicitly chose: "Keep house data private; publish only app code". Do not commit the `private/` directory, photos, DXFs, generated models, private configuration, property coordinates, API keys or databases. The initial private package is prepared locally and will be transferred separately to the Pi by the parent task. It has `data/project.json`, `data/plot.json`, and `source/` with original DXFs/front/rear/overhead images. `HOUSE_DATA_DIR` points to its root. The source code has been separated from this data; do not reintroduce project-specific constants. Use synthetic fixtures for public tests.

Add authentication before public deployment, protect every photo/model/reference/report/upload/process/revision endpoint, CSRF and origin checks for mutations, upload size/count limits and file decoding validation. Use persistent secrets and secure cookies over HTTPS. Disable private-data caching in the service worker: cache only the public app shell/static assets; offline photo drafts should stay on the same device, clearly indicate unsynced items, and sync explicitly/reliably. Do not cache authenticated responses or secrets. The unauthenticated page must reveal no private model or photographs.

This is a Flask/Pi deployment, not a Sites-hosted rewrite. PiDash normally creates a systemd service as user `hammonja` with an `app.py` entry point and project venv if available. Production must use a suitable WSGI server and a durable worker (or a carefully controlled single-process persistent-job worker). Use localhost binding and the Cloudflare tunnel; avoid opening new public ports. Parent task owns PiDash/Cloudflare site registration and initial private-data transfer. Do not independently register duplicate sites or change PiDash infrastructure without coordination.

## Verification and delivery

Use isolated synthetic data and mock OpenAI responses for deterministic tests: authentication/CSRF, safe file handling, job recovery/failures, schema rejection, actual scene update/revision/revert, missing-key behavior, chunk coverage and privacy. Validate API request shape against official current docs. Add a real API smoke check only if a configured key is available; report clearly if not run. Validate installability/manifest/service worker and camera fallback; state if actual mobile camera was not exercised. Test existing viewer behavior remains intact. Do not use real house photos in public CI fixtures.

The baseline currently requires private data at import time. Implement a safe first-run/missing-data state so cloud tests and deployment can start without it. A private data import/restore mechanism can support the initial transfer, but must be authenticated and prevent zip traversal/zip bombs/overwriting app code. No publicly reachable unauthenticated setup path.

Work on the repository's main branch if safe and authorized by the release request; preserve existing changes and push completed code. If a PR is needed, attach it to the task. Report exact commit, tests, deployment status and any remaining credential/access blockers. Never report a mock API result or a local-only build as a live end-to-end deployment.

Official references checked:
- https://developers.openai.com/api/docs/models/gpt-6-astra
- https://developers.openai.com/api/docs/guides/images-vision
- https://learn.chatgpt.com/docs/environments/cloud-environments
