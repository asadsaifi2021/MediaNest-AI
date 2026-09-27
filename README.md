# Media Archive Cloud API

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
- `POST /api/v1/media/search-face` — user-scoped cosine-similarity search.

POST requests are signed over the exact transmitted bytes:

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

Run both migrations in the Supabase SQL Editor before using the API. The first
enables pgvector, creates
the metadata and face tables plus indexes, and installs two server-only RPCs.
The synchronization RPC performs the metadata upsert and face replacement in a
single transaction. A unique `(user_id, device_id, local_file_id)` constraint
makes retries idempotent.

Media ownership always comes from the verified JWT `sub` claim. The sync API
does not accept `user_id`, so a device cannot select another user's namespace.
Face embeddings must contain exactly 512 finite values. If the edge model uses
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
