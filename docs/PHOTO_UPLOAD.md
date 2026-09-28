# First photo upload on this Windows PC

The single-PC flow supports JPEG, PNG and non-animated WebP, at most 20 MiB
and 20 million pixels per photo. AI tags, video/audio uploads, background jobs,
resumable transfers, and remote-device setup are not implemented.

## Configured on this machine

- The registered windows-pc node uses http://127.0.0.1:8100.
- A dedicated `local-media` directory in the repository holds originals,
  thumbnails and recovery manifests. It is ignored by Git. Back it up separately.
- Root `.env` has LOCAL_NODE_ID and a random LOCAL_NODE_SECRET.
- `local_storage/.env` has the matching values, MEDIA_ROOT and METADATA_API_URL.
  It contains no Supabase service-role key. Never share either environment file.
- Supabase migrations through 005 are required. Existing projects run only the
  unapplied migration, not the entire setup.sql bundle.

## Start after closing/restarting the application

From the repository root, use two terminals:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```powershell
.venv\Scripts\python.exe -m uvicorn local_storage.main:app --host 127.0.0.1 --port 8100
```

Use a single storage worker. Do not run multiple workers against the same directory.
If a port is already occupied by this service, do not launch a second instance.
In a third terminal start React with `cd frontend` then `npm run dev`.

Open the app, sign in, select **Your library → Add media**, choose **This Windows
PC**, choose one photo, then **Upload photo**. The dialog closes after local
storage and metadata synchronization succeed. Click the new gallery item to
view its metadata, then **View original photo** to load the original locally.

## Security and recovery

The metadata API issues account-, node-, resource- and action-scoped grants.
The browser sends raw photo bytes only to the local service. Permissions expire
after 15 minutes for uploads and 2 minutes for reads. Every operation also
checks the registered node online; disabled nodes are denied. Bytes already
downloaded into a browser cannot be revoked.

Only UUIDs are used for disk paths; original filenames are metadata. Linked
paths are refused. Originals are preserved byte-for-byte. Pillow validates the
actual format and strips metadata when generating a 640px JPEG thumbnail.
The service is bound to loopback and allows only the development frontend origins.
For remote access, configure private HTTPS origins before exposing this service.
Do not expose port 8100 directly to the public Internet.

Upload completion atomically writes media and object references to Supabase.
If synchronization fails, saved local files and the manifest remain. Retry in
the same dialog without selecting a different file to reuse the upload ID.
Closing the dialog loses its in-memory upload ID; automatic background recovery
is not implemented. Do not delete saved originals to fix a sync failure.
Interrupted processes may leave .incoming staging directories requiring manual
review. This first version has no retention/quota management; monitor disk space.

The node secret is provisioned manually for one PC. Rotate it in both private
environment files and restart both services to invalidate grants. A multi-node
enrollment/revocation UI is a later feature. No migration stores this secret.

Tests cover actual local file writes and HTTP routes with an isolated metadata
test double, plus actual SQL transactions in embedded PostgreSQL/pgvector and
mocked desktop/mobile browser flows. A user's live first-photo test is separate.
