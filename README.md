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

Keep `SUPABASE_SERVICE_ROLE_KEY` and `EDGE_HMAC_SECRET` server-side. Create the
table with:

```sql
create table public.archive_events (
  id uuid primary key,
  asset_id uuid not null,
  event_type text not null check (event_type in
    ('discovered', 'indexed', 'uploaded', 'deleted', 'failed')),
  device_id text not null,
  occurred_at timestamptz not null,
  metadata jsonb not null default '{}'::jsonb,
  user_id text not null,
  created_at timestamptz not null default now()
);
create index archive_events_user_time_idx
  on public.archive_events (user_id, occurred_at desc);
```

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

Supabase calls and PyJWT's synchronous JWKS retrieval run in AnyIO worker
threads. JWKS documents use a bounded TTL; per-key indefinite caching is off so
key rotation continues to work.

## Media search database

Run [the media-search migration](supabase/migrations/001_media_search.sql) in the
Supabase SQL Editor before using `/api/v1/media/*`. It enables pgvector, creates
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
