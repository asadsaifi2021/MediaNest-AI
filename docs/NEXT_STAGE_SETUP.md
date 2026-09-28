# Enable tags, video/audio, local AI and private installation

The code is implemented; hosted migrations, FFmpeg/model installation and
Tailscale enrollment are separate activation steps. Do not assume an adapter
unit test means a model was downloaded or benchmarked on your hardware.
Existing photos and credentials are preserved.

## 1. Apply the new database migrations

In your existing Supabase project's SQL Editor, run these files **once, in order**:

1. `supabase/migrations/006_search.sql`
2. `supabase/migrations/007_media_upload.sql`
3. `supabase/migrations/008_local_indexing.sql`

Back up first. Do not rerun 001–005 or the fresh-project setup.sql on your
existing project. These migrations add columns/functions, not media storage.
Restart the metadata API after updating the code.

## 2. Try tags and search

Open a photo in Your library. Edit its comma-separated tags and choose Save tags.
The main search box now searches filenames and tags case-insensitively, plus
transcript words/phrases. Tag chips still apply exact tag filters.
AI suggestions are separate from your hand-edited tags.

## 3. Enable video/audio on the Windows storage PC

Install FFmpeg and ffprobe from a Windows build linked by
[FFmpeg's download page](https://www.ffmpeg.org/download.html). Ensure both
executables are on PATH, then reopen the VS Code terminals. Verify:

```powershell
ffmpeg -version
ffprobe -version
```

From the repository root, run the services in separate terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
.\.venv\Scripts\python.exe -m uvicorn local_storage.main:app --host 127.0.0.1 --port 8100
```

The frontend still runs with `npm run dev` from `frontend`.
Add media accepts JPEG/PNG/WebP up to 20 MiB and MP4/WebM/MOV/MP3/M4A/WAV/FLAC/OGG
up to 256 MiB. One transfer runs at a time. Video/audio processing is bounded to
four-hour inputs and ten minutes per FFmpeg command; large/slow conversions may
be rejected. Originals are unchanged. Video gets a local poster and H.264/AAC
MP4 playback copy; audio gets a local neutral cover and AAC playback copy.
Duration, source codecs and dimensions are metadata.

Keep the upload dialog open until conversion completes. Transfers themselves
are **not resumable**. A completed local file whose metadata sync fails is
recoverable by the worker below, even after the browser grant expires.
A crash during transfer/conversion can leave a hidden .incoming-* directory;
there is no automatic deletion or salvage of incomplete uploads.

Playback uses HTTP Range requests and two-minute, file-scoped HttpOnly cookies.
The player renews authorization while mounted; revocation is checked by the
storage service on each request. A stream already in progress is not forcibly
terminated by disabling a node. Closing/suspending the app can expire playback;
Reconnect playback requests fresh authorization.

## 4. Install local AI dependencies and weights

AI is optional; normal browsing/uploads do not import AI libraries.
From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

Expect a substantial download for PyTorch and other inference dependencies.
Do not install these packages on the cloud API. The worker uses CPU inference
initially, not a claim of real-time performance.

Obtain model files from their official publishers and retain their license
notices. Place them in a dedicated folder (for example C:/MediaNestModels):

- **YOLOv8n:** choose the detection weights `yolov8n.pt` linked from
  [Ultralytics YOLOv8](https://docs.ultralytics.com/models/yolov8/).
  Review [Ultralytics licensing](https://www.ultralytics.com/license).
  Personal use does not waive license conditions; review again before sharing,
  hosting for others, or distributing. This repository's MIT notice does not
  relicense Ultralytics. We have not changed the project's license.
- **Speech:** download a complete
  [faster-whisper model directory](https://github.com/SYSTRAN/faster-whisper)
  such as Systran/faster-whisper-base, including model.bin, config.json,
  tokenizer.json and vocabulary files, from its linked Hugging Face repository.
  The adapter uses local_files_only=True and never sends speech to a cloud API.
- **Faces:** obtain the full ONNX files for
  [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
  and [SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface)
  from OpenCV Zoo. Download the real LFS assets, not pointer text. Review each
  model folder's license. This implementation does not use InsightFace weights.

Add these to the existing `local_storage/.env`, retaining its existing node
settings and secret:

```dotenv
YOLO_MODEL_PATH=C:/MediaNestModels/yolov8n.pt
YOLO_LICENSE_ACCEPTED=true
WHISPER_MODEL_PATH=C:/MediaNestModels/faster-whisper-base
YUNET_MODEL_PATH=C:/MediaNestModels/face_detection_yunet_2023mar.onnx
SFACE_MODEL_PATH=C:/MediaNestModels/face_recognition_sface_2021dec.onnx
ENABLE_FACE_RECOGNITION=true
```

Only set the license acknowledgement after reviewing it. Leave face recognition
false unless you want it; the UI also requires per-file consent before processing.
Model files must already exist. There are no implicit model downloads during
indexing. Only use trusted weights: PyTorch model files can contain executable
serialized code.

Start one worker in a third terminal:

```powershell
.\.venv\Scripts\python.exe -m local_storage.worker
```

Its durable SQLite queue is in ignored `local-state`, on the PC's local disk.
Do not put the SQLite database on a shared network drive. A process lock prevents
two workers using the same queue. Interrupted running jobs resume after restart;
completed inference results survive metadata-network failures without rerunning
inference. Processing failures retry, then report Failed after three attempts.
Correct the setup and queue the file again to retry a terminal failure.
Do not run with the browser user's credentials or a Supabase service key.

Open a media item → Local AI processing → choose options → Queue local indexing.
YOLO labels supported common objects, **not arbitrary scenes such as mountains**.
Videos sample at most 30 evenly spaced frames, so brief objects/faces may be missed.
Transcripts include segment timestamps and are searchable. Whisper can produce
incorrect words; review before relying on a transcript.

For faces, go to Face search, select Find similar faces, inspect the local face
crops, select matches yourself and assign a name. Nothing is named automatically.
Similarity is not probability; calibrate the threshold on your own photos.
SFace's 128-D features are zero-padded into the existing 512-D database field,
which preserves cosine distance. The model ID includes both model file hashes,
so they cannot be mixed with InsightFace or legacy embeddings. Stable face IDs
preserve confirmed names for identical re-indexing. Changing models/detections
can replace IDs and require new name confirmation.

Forget faces deletes that file's cloud embeddings/names and invalidates in-flight
results. Original media and local crop files remain on your private disk; access
to old crop files is denied once their embedding record is deleted.
Queue again only if you want face indexing re-enabled.

## 5. Private HTTPS access and installation

No public tunnel or firewall opening has been configured by the application.
Use [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve),
not Funnel. Install Tailscale on the PC and phone, sign in, approve devices,
enable HTTPS/MagicDNS, and restrict tailnet access to the intended family
devices/users. Network membership does not replace MediaNest login/ownership.
Separate MediaNest users have separate archives; shared family albums are not
implemented.

For the simplest private deployment, serve the built React app from the existing
metadata API on your PC; Supabase remains the metadata database.
Leave VITE_API_URL empty, then:

```powershell
cd frontend
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

Do not run a second API on a port already occupied; stop the development instance
first. Restart the API after each production build. Start storage similarly:

```powershell
.\.venv\Scripts\python.exe -m uvicorn local_storage.main:app --host 127.0.0.1 --port 8100 --proxy-headers --forwarded-allow-ips 127.0.0.1
tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale serve --bg --https=8443 http://127.0.0.1:8100
tailscale serve status
```

Use the actual HTTPS hostname Tailscale displays, not a guessed hostname.
Set CORS_ORIGINS in **both** root .env and local_storage/.env to a JSON array
containing that frontend origin, e.g. `["https://your-pc.your-tailnet.ts.net"]`.
Retain localhost origins only if needed. Restart both services.
In Connections → Change storage address, set the existing node's address to
`https://your-pc.your-tailnet.ts.net:8443`. Do not register a second node or
change its UUID/secret. Cookies require app and storage to use the same hostname
and scheme (different ports are okay).

In Supabase Auth URL Configuration, add that app origin to Site URL and add
its `/auth/callback` and `/auth/reset-password` URLs to the redirect allowlist.
Keep development redirects if still needed.

On the phone, connect Tailscale and open the app HTTPS address. Sign in; upload a
short clip; seek during playback; verify tags/search. Then choose Install app
in Chrome (Android), or Apps → Install in Edge (Windows).
The manifest/service worker are production-build features. The service worker
caches **only a generic offline document**. It never stores API replies,
auth credentials or private media in Cache Storage. Auth session persistence
still uses Supabase's existing browser storage.

This setup requires the PC awake, services running, and Tailscale connected.
It is private access, not public hosting or a guarantee of direct P2P; relays
may be used. No monthly cloud-hosting or lifetime-free promise is made.

## Verification boundaries

Automated tests cover ownership, SQL migrations, tags/search, AI result consent
and stale jobs, queue restart/retry, and scoped playback/range delivery.
FFmpeg/model inference and phone installation require their dependencies and
real-device tests. A mocked decoder/browser response is not a hardware benchmark.
There is still no batch/resumable transfer, cross-ID deduplication, automatic
folder watching, general media deletion, shared albums or semantic scene model.
