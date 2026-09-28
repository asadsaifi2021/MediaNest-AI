# First local-storage milestone: register this Windows PC

This page covers registration only. For the now-implemented single-PC photo
service, continue to [first photo upload](PHOTO_UPLOAD.md). Registration itself
does not start a service or upload files.

## Enable registration on your existing project

1. Open Supabase's SQL Editor.
2. Run only `supabase/migrations/004_storage_registry.sql`, once.
   Do not rerun `setup.sql` on your already initialized project.
3. Restart the metadata backend if it is not running with `--reload`.
4. Refresh MediaNest AI and open **Connections**.
5. In **Register your local storage**, keep:
   - Storage name: `This Windows PC`
   - Device ID: `windows-pc`
   - Storage server address: `http://127.0.0.1:8100`
6. Click **Register storage** once. The record should say **Registered ·
   connectivity not verified**.

The address is reserved for the upcoming local service. It is not a folder
path and no service is started by registration. Do not put passwords in it.
Localhost works only on this PC; other devices need a private HTTPS address.
Disabling a registration preserves its references and never deletes files.
Choose a new device ID if you need another registration; editing/re-enabling
registrations is not implemented.

## What is stored centrally?

`storage_nodes` contains your user ID, device ID, display name, server origin,
creation time, and disabled time. `media_objects` defines future original,
thumbnail, and playback references using opaque UUID object keys, byte sizes,
MIME types, and optional SHA-256 checksums. Composite foreign keys prevent
cross-account media/node references. These tables contain no file bytes or
local filesystem paths. Existing metadata records are unchanged.

Both tables deny direct browser access through RLS and grants. The API derives
ownership from the verified user's JWT. Registering an origin never causes
the backend to fetch it, and does not prove ownership of that server.

## Photo service

The single-PC photo service, scoped grants and thumbnail flow are now implemented;
follow [the photo guide](PHOTO_UPLOAD.md) to configure and test them. The remaining
notes describe the boundary between registration and trusted storage.

Build the local service with an explicit dedicated directory on this Windows
PC, independently revocable node credentials, and short-lived file-scoped
upload/access grants. Then implement one-photo upload, a locally generated
thumbnail, and metadata synchronization. The local service must check grants,
enforce the configured directory boundary, and reject disabled nodes before
serving bytes. Registration alone is not authenticated device enrollment.

A dedicated local-media directory is now configured on the development PC.
Existing photo folders are never scanned automatically.
