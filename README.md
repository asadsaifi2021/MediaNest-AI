# MediaNest AI

Your media. Your storage. Easily found.

MediaNest AI is a React application in development for organizing and searching photos,
videos, and audio while keeping all media files on the owner's local storage.
Android, Windows, and web access will start with a responsive React PWA.

## Product boundaries

- Originals, thumbnails, and converted playback files stay on the local NAS.
- The server stores searchable metadata, tags, transcripts, face vectors,
  ownership, and references to storage objects.
- Browsers transfer media directly to an authorized local storage service.
- AI indexing runs on the local server, not in the cloud API or React frontend.
- The first deployment targets personal/family use over Tailscale.
- Minimize recurring costs; do not assume cloud free tiers last forever.

## Current status

This repository currently contains the FastAPI metadata backend inherited from
[Noor Saifi's Media Archive Cloud API](https://github.com/noorsaifi/media-archive-cloud-api),
including the Supabase integration changes. Original copyright and Git history
are preserved. The React frontend now includes sign-in, an explicitly labeled
sample library, authenticated gallery browsing, exact tag/type filters,
pagination, media details, a face-vector search form, activity, and connection status.
Connections now supports owner-scoped storage registration and disabling.
See [Windows PC storage setup](docs/LOCAL_STORAGE.md); existing projects need
migration 004. Registration does not prove connectivity or enroll a trusted node.
The single-PC photo flow now includes scoped upload/read grants, a local service,
JPEG/PNG/WebP uploads, local thumbnails, and authorized gallery previews.
See [first photo upload](docs/PHOTO_UPLOAD.md). Migration 005 and the local
service configuration are required. The AI worker, video/audio upload/playback,
remote-device access, and PWA installation are future milestones.
The configured development project's database connectivity has been verified;
user sign-in is working. Two-user live isolation testing is still pending.

## Run the frontend

Requires Node.js 22+. From the repository root:

```powershell
cd frontend
npm ci
npm run dev
```

`npm start` is an alias for `npm run dev`; both run from the `frontend` folder.

Open http://127.0.0.1:5173 and choose **Explore sample library**. No credentials
are needed for this preview. Its illustrations are bundled locally; sample
records never enter the database or appear in a signed-in user's library.

To sign in to your real archive, copy `frontend/.env.example` to
`frontend/.env.local`, set `VITE_SUPABASE_URL` and
`VITE_SUPABASE_PUBLISHABLE_KEY`, and restart Vite. Use an existing Supabase
email/password account, or choose Create an account after completing
[authentication setup](docs/AUTH_SETUP.md). Sign-up, confirmation resend,
password recovery and new-password forms are implemented.
The sidebar's **Account** page supports profile, email, password and session
settings. See [account settings](docs/ACCOUNT_SETTINGS.md) for confirmation
requirements and current limits.
Only an `sb_publishable_` key belongs in the frontend.
The backend needs its own secret key, configured separately as described below.

Run the backend in a second terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Vite proxies API requests to port 8000. The sample library can be explored even
if the backend is offline; Connections displays the actual backend status.
VS Code also has **MediaNest AI: Run frontend**, **Run API**, and test/build tasks.
Install dependencies before running these tasks.

## Frontend verification and deployment

```powershell
cd frontend
npm run build
npm test
npx playwright install chromium
npm run test:e2e
```

Browser tests run on port 5174 with synthetic auth/API responses. They verify
desktop/mobile behavior, filtering, dialogs, and account switching, not live
Supabase connectivity. Keep port 5174 available during the test run.

For deployment, set `VITE_API_URL` to the HTTPS metadata API origin before
building. Configure backend `CORS_ORIGINS` as a JSON array of approved frontend
origins. Serve `frontend/dist` with a fallback to `index.html` for React routes.
Frontend environment variables are public build-time configuration. Never put
server secrets or HMAC keys in any `VITE_*` variable. Private query results
are held in memory and cleared on account changes; they are not persisted in
a service worker or local database.

See [architecture](docs/ARCHITECTURE.md) and [roadmap](docs/ROADMAP.md) before
adding features. The existing thumbnail URL field is metadata only; future
storage integration should use stable node/object references and temporary
authorized URLs, not cloud-hosted thumbnails.

## Metadata backend

FastAPI backend for a hybrid media archive. Edge devices authenticate a user
with a Supabase JWT and sign mutation bodies with a shared HMAC secret. The API
stores archive lifecycle events in Supabase without blocking the async event loop.

## Setup

Requires Python 3.11+ and a Supabase project.

```bash
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Keep `SUPABASE_SECRET_KEY` and `EDGE_HMAC_SECRET` server-side. Never place them
in a browser, desktop client, or mobile application. A legacy
`SUPABASE_SERVICE_ROLE_KEY` is also accepted during migration.

In the Supabase SQL Editor, run the migration files in numeric order:

```text
supabase/migrations/001_media_search.sql
supabase/migrations/002_archive_events.sql
supabase/migrations/003_database_integrity.sql
supabase/migrations/004_storage_registry.sql
```

Then start the API and request `GET /db-health`. A successful response is
`{"status":"connected","database":"supabase"}`. If the migrations are missing,
the endpoint reports that the schema is not initialized instead of masking the
condition as a network error.

## API and signing

- `GET /health` — public liveness check.
- `GET /db-health` — Supabase Data API connectivity/readiness check.
- `GET /api/v1/archive-events?limit=50` — authenticated event listing.
- `POST /api/v1/archive-events` — JWT plus edge HMAC protected event creation.
- `POST /api/v1/media/sync` — idempotent metadata and face-vector synchronization;
  requires both JWT and edge HMAC authentication.
- `GET /api/v1/media/search?tag=...` — paginated, user-scoped tag search.
- `GET /api/v1/media` — owner-scoped gallery with type/tag filters, ordering,
  offset/limit pagination, and `has_more`.
- `GET /api/v1/media/{media_id}` — owner-scoped metadata detail; returns 404
  for nonexistent or another user's records.
- `POST /api/v1/media/search-face` — user-scoped cosine-similarity search.

Mutation requests to archive-events and media/sync are signed over the exact
transmitted bytes (search-face does not require an edge signature):

```text
hex(HMAC-SHA256(EDGE_HMAC_SECRET, X-Edge-Timestamp + "." + raw_body))
```

Send the digest in `X-Edge-Signature` as hex or `sha256=<hex>`. The timestamp is
Unix seconds and must be within `EDGE_SIGNATURE_MAX_AGE_SECONDS`.

Supabase calls and synchronous JWT verification run in AnyIO worker threads.
Asymmetric RS256, ES256, and EdDSA access tokens are verified from the JWKS
endpoint. HS256 access tokens are verified through Supabase Auth, supporting
legacy and shared-secret signing configurations without copying a signing
secret into this service.

## Media search database

Follow [the Supabase setup guide](docs/SUPABASE_SETUP.md) to create your project,
apply all migrations, configure both environments, and verify connectivity.
New projects can use the generated `supabase/setup.sql` bundle once.
The first migration
enables pgvector, creates
the metadata and face tables plus indexes, and installs two server-only RPCs.
The synchronization RPC performs the metadata upsert and face replacement in a
single transaction. A unique `(user_id, device_id, local_file_id)` constraint
makes retries idempotent.

Media ownership always comes from the verified JWT `sub` claim. The sync API
does not accept `user_id`, so a device cannot select another user's namespace.
Face embeddings must contain exactly 512 finite values and must not be zero.
Ingest/search use matching `model_id` and `vector_version` values to isolate
different vector spaces. Owners reference actual Supabase Auth users.
If the edge model uses
a different dimension, update the validators and migration together before
deploying.

## Tests

```bash
pytest -q
```

Tests use `httpx.AsyncClient`, a generated RSA key, mocked JWKS resolution, and
an in-memory Supabase double. They require no network or real project.

To run the opt-in smoke test against the project configured in `.env`:

```powershell
$env:RUN_SUPABASE_INTEGRATION="1"
pytest -q tests/test_supabase_integration.py
```
