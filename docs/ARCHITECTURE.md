# MediaNest AI architecture

## Target components

| Component | Technology | Responsibility |
| --- | --- | --- |
| Frontend | React, TypeScript, Vite, React Router, TanStack Query | Responsive gallery, login, search, uploads, playback; installable production PWA |
| Metadata API | Python FastAPI | Verify users, enforce ownership, search and sync metadata |
| Metadata database | Supabase PostgreSQL, pgvector, full-text search | Records, tags, transcripts, vectors, storage references |
| Identity | Supabase Auth | User login and session tokens |
| Storage service | Local FastAPI service and NAS filesystem | Authorized uploads, thumbnails, downloads, range streaming |
| Worker | Python, SQLite job queue, FFmpeg, Pillow | Durable jobs, extraction, thumbnails, retries, metadata sync |
| Private remote access | Tailscale and HTTPS | Family devices access home storage |

## Data ownership and flow

All media bytes, including thumbnails and playback derivatives, remain on the
owner's storage. The cloud API does not proxy media uploads or playback.
Supabase holds the central searchable metadata. SQLite is operational job state,
not a second authoritative metadata database.

1. React signs the user in with Supabase Auth.
2. React asks the metadata API for authorization to upload to a registered node.
3. The storage service validates a short-lived, file-scoped authorization and
   accepts bytes directly from the browser.
4. A persistent local job indexes the completed file and synchronizes metadata.
5. Search queries go to the metadata API.
6. After ownership checks, the API grants temporary access that the storage
   service independently validates before serving media.

Store stable media IDs, storage node IDs, and opaque object keys. Never accept
an arbitrary filesystem path from the browser. Plan resumable uploads,
idempotent synchronization, deletion propagation, and model-version tracking.
When the NAS is offline, metadata remains searchable but media is unavailable.

## Authentication boundaries

The browser receives only public configuration and user session credentials.
Supabase secret/service-role keys and worker secrets stay on trusted servers.
Current database access uses a privileged backend key, so API ownership filters
are essential: RLS does not protect requests made with that key.
Each local node will need independently revocable credentials; the inherited
shared HMAC mechanism is an initial backend feature, not final device enrollment.
Do not put that HMAC secret in React.

Use HTTPS and specific allowed frontend origins. Network membership alone does
not replace per-user file authorization. Tailscale is private network access,
not a promise that every connection is direct P2P; relays may be needed.

## AI plan

The first adapters are now implemented in local_storage/ai.py: optional YOLOv8
object detection, faster-whisper CPU speech transcription, and OpenCV YuNet/SFace
face extraction with per-file consent. The worker persists job state in local
SQLite and synchronizes only metadata. See NEXT_STAGE_SETUP.md for activation
and verification boundaries. AI tags are separate from user tags; face results
are reviewed/named manually, with no automatic identity assertion.
Node-authenticated recovery derives ownership from the registered node rather
than a browser session. Disabled nodes cannot synchronize or serve new reads.

Evaluate YOLO for common objects, a CLIP-style model for broader scene search,
faster-whisper for transcription, and a licensed face-embedding model.
Choose weights after confirming licensing and benchmarking actual hardware.
InsightFace's source license does not grant unrestricted use of its pretrained
weights. Do not assume standard COCO detection covers trees or mountains.
Keep different embedding models in separate vector spaces, with model/version
identifiers; 512 dimensions is currently a face-schema choice, not a universal
embedding dimension.

## Deployment and scope

Start with a browser app and manual uploads. Background phone backup and
continuous desktop folder watching require separate platform work.
Host the static frontend and metadata API separately from the local storage
service. Cloud hosting provider selection is deferred until resource usage
and current pricing are checked. No lifetime-free guarantee is assumed.

Prefer a small number of services. No Django rewrite, second vector database,
Redis/Celery cluster, or native wrappers are planned for the first milestone.
Back up both NAS files and server metadata; neither substitutes for the other.
