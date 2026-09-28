# MediaNest AI: create and connect your database

No Supabase account/project credentials are included in this repository.
Local database tests do not establish a hosted connection.

## 1. Create your own project

Sign in at https://supabase.com/dashboard and create a project named
**MediaNest AI** under your own organization. Choose a region near your users,
review the currently available plan, and store the database password in a
password manager. Wait until the project is ready. Do not send passwords or
secret keys in chat. Free-tier limits and availability can change.

## 2. Install the schema

For a **new, empty project**, open `supabase/setup.sql` in VS Code, copy its
contents into the project's SQL Editor, and run it once as the default
database administrator. This file is generated from migrations 001–004.
Do not create Supabase Storage buckets: all media bytes stay on your NAS.

For an existing project, back up first and apply only the unapplied files in
`supabase/migrations`, in numeric order. Migration 003 is transactional and
will stop if old owners are not real Supabase Auth users, a face belongs to a
different owner than its media, or existing data violates the new constraints.
Correct those records deliberately; do not delete them to bypass an error.
Never rerun 001 after 003: it would replace newer RPC implementations.

Do not mix manual SQL Editor installation and CLI migration tracking without
reconciling migration history first. The optional `supabase/config.toml` is for
local CLI development (requires Docker); it does not configure a hosted project.

## 3. Configure the backend

Copy the root `.env.example` to `.env` if it does not already exist.
From the project's Connect dialog/settings, find the project URL. Under
**Settings → API Keys**, find/create the publishable and secret keys.
In the root `.env`, set:

```dotenv
SUPABASE_URL=https://YOUR-PROJECT-REF.supabase.co
SUPABASE_SECRET_KEY=YOUR_SERVER_ONLY_SECRET_KEY
```

Also replace `EDGE_HMAC_SECRET` with a securely generated random secret, for
example the output of `python -c "import secrets; print(secrets.token_hex(32))"`.
Only the backend and trusted local worker receive that value, never React.
Keep the other development defaults. The database password is not an API key.

## 4. Configure React and your first account

Copy `frontend/.env.example` to `frontend/.env.local` if absent. Set
`VITE_SUPABASE_URL` to the same project URL and
`VITE_SUPABASE_PUBLISHABLE_KEY` to the `sb_publishable_...` key.
Never put a secret/service-role key in a `VITE_*` variable.

In Supabase **Authentication → Users**, create your own email/password user.
Complete email confirmation if required. For a private family archive,
disable public sign-ups in Authentication settings and add users explicitly.
Set the Auth Site URL to `http://127.0.0.1:5173` for local development; add
`http://localhost:5173` as an allowed redirect if you use it.
Use your exact HTTPS origins when deploying.

Restart both the API and Vite after changing environment files. Sign in to
the app with the account you created. An empty real library is expected:
sample preview data is never inserted, and the NAS/AI worker is not built yet.

## 5. Verify the live connection

From the repository root, start the API:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000/db-health. Expect:
`{"status":"connected","database":"supabase"}`.
This checks all three tables and the versioned face-search RPC, not just
whether the API process is running.

Optional read-only live smoke test, from another terminal:

```powershell
$env:RUN_SUPABASE_INTEGRATION="1"
.venv\Scripts\python.exe -m pytest -q tests/test_supabase_integration.py
Remove-Item Env:RUN_SUPABASE_INTEGRATION
```

A successful health check does not prove user sign-in, email delivery, or
NAS access. Verify two real users' sign-in and isolation before deployment.

## Database behavior and boundaries

For storage registration on an existing project, apply migration 004 only and
follow [Windows PC storage setup](LOCAL_STORAGE.md). Registration does not
start the storage service or enable uploads.

- Metadata, transcripts, tags, 512-dimensional face vectors, and events only.
- Owners reference Supabase Auth users. Deleting an Auth user cascades their
  database records; it does **not** delete NAS files.
- `device_id` plus `local_file_id` identifies a storage object, not permission
  to read an arbitrary filesystem path. NAS registration/access grants remain
  a later milestone. Do not store permanent signed URLs or storage passwords.
- All tables use RLS with no browser policies, and browser table/RPC grants are
  revoked. Requests must go through FastAPI. The server key bypasses RLS, so
  API ownership filters remain mandatory.
- Sync replaces a media record's entire face set atomically. Retries reuse its
  ID. Concurrent sync uses database row locking; stale-worker revision handling
  and deletion propagation are not implemented.
- Face ingest/search accepts `model_id` and `vector_version`; both must match.
  `legacy-512` is only a compatibility label, not a chosen recognition model.
  Zero vectors are rejected. Search uses exact owner-filtered ranking for now.
- Transcript full-text indexing is installed; a transcript search UI/API is
  still a future feature.
- Back up metadata and NAS files separately. Embeddings/transcripts are private
  data even though they are not original media.

## Repeatable local checks (no account required)

```powershell
cd supabase
npm ci
npm test
node build-setup.mjs --check
```

Tests execute SQL against embedded PostgreSQL with pgvector. Test-only Auth
tables/roles simulate Supabase ownership, but not its hosted gateway or Auth
service. They cover fresh setup, upgrades, atomic rollback, user/model isolation,
permissions, and cascade deletion. Regenerate the bundle after migration edits
with `node supabase/build-setup.mjs` from the repository root.

Official references:
- https://supabase.com/docs/guides/getting-started/api-keys
- https://supabase.com/docs/guides/database/postgres/row-level-security
- https://supabase.com/docs/guides/deployment/database-migrations
