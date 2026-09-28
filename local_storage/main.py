"""Photo bytes stay here. This service has no Supabase service-role key."""
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import threading
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

import httpx
from anyio import to_thread
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.transfers import MAX_BYTES, decode_grant

ROOT = Path(__file__).resolve().parents[1]


class LocalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / "local_storage" / ".env", extra="ignore")
    local_node_id: UUID
    local_node_secret: SecretStr
    media_root: Path = ROOT / "local-media"
    metadata_api_url: str = "http://127.0.0.1:8000"
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]


@lru_cache
def get_local_settings() -> LocalSettings:
    return LocalSettings()


def create_app() -> FastAPI:
    service = FastAPI(title="MediaNest local photo storage", docs_url=None, redoc_url=None)
    # Fixed development origins; remote access needs explicit HTTPS configuration.
    service.add_middleware(CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
    service.include_router(router)
    return service


from fastapi import APIRouter  # noqa: E402

router = APIRouter()
Config = Annotated[LocalSettings, Depends(get_local_settings)]
# Deliberately one transfer at a time in this first single-worker service.
upload_lock = threading.Lock()
TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
Image.MAX_IMAGE_PIXELS = 20_000_000


def authorization(request: Request, settings: LocalSettings, purpose: str) -> tuple[str, dict]:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    key = settings.local_node_secret.get_secret_value()
    if len(key) < 32:
        raise HTTPException(503, "Storage secret is not configured securely")
    claims = decode_grant(token, key, str(settings.local_node_id))
    if claims["purpose"] != purpose:
        raise HTTPException(403, "Wrong file permission")
    return token, claims


def metadata_call(settings: LocalSettings, token: str, path: str, payload: dict) -> dict:
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(settings.local_node_secret.get_secret_value().encode(),
        ("POST:" + path + ":" + token + ":").encode() + body, hashlib.sha256).hexdigest()
    try:
        response = httpx.post(settings.metadata_api_url.rstrip("/") + path, content=body,
            headers={"Authorization": "Bearer " + token, "X-Node-Signature": signature,
                     "Content-Type": "application/json"}, timeout=20, follow_redirects=False)
    except httpx.RequestError as exc:
        raise HTTPException(503, "Metadata API is offline. Any saved local files are preserved.") from exc
    if response.status_code != 200:
        detail = "Storage authorization or metadata synchronization failed"
        try:
            value = response.json().get("detail")
            if isinstance(value, str):
                detail = value
        except ValueError:
            pass
        raise HTTPException(response.status_code, detail)
    return response.json()


def media_directory(settings: LocalSettings, claims: dict) -> Path:
    root = settings.media_root.absolute()
    if not root.is_absolute() or root.is_symlink():
        raise HTTPException(503, "Media directory must be a dedicated non-symlink directory")
    root.mkdir(parents=True, exist_ok=True)
    # UUID-only components; never use the uploaded filename for filesystem access.
    candidate = root / str(UUID(claims["sub"])) / str(UUID(claims["media_id"]))
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
           for p in [candidate, *candidate.parents]):
        raise HTTPException(403, "Linked media paths are not allowed")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise HTTPException(403, "Invalid media path")
    return candidate


def process_photo(stage: Path, claims: dict, sha256: str) -> dict:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(stage / "original") as image:
                if image.format not in TYPES or TYPES[image.format] != claims["content_type"]:
                    raise HTTPException(415, "File contents do not match the supported photo type")
                if getattr(image, "n_frames", 1) != 1:
                    raise HTTPException(415, "Animated images are not supported yet")
                image.load()
                thumbnail = ImageOps.exif_transpose(image).convert("RGB")
                thumbnail.thumbnail((640, 640))
                # Fresh pixel buffer strips EXIF, GPS, text chunks and profiles.
                clean = Image.new("RGB", thumbnail.size)
                clean.paste(thumbnail)
                clean.save(stage / "thumbnail.jpg", "JPEG", quality=82)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise HTTPException(415, "Photo is invalid, too large in pixels, or unsupported") from exc
    thumb = (stage / "thumbnail.jpg").read_bytes()
    return {"original_sha256": sha256, "thumbnail_sha256": hashlib.sha256(thumb).hexdigest(),
            "thumbnail_size": len(thumb)}


@router.get("/health")
async def health(settings: Config) -> dict:
    return {"status": "ok", "node_id": str(settings.local_node_id)}


@router.post("/upload")
async def upload(request: Request, settings: Config) -> dict:
    token, claims = authorization(request, settings, "upload")
    if not 1 <= claims.get("byte_size", 0) <= MAX_BYTES:
        raise HTTPException(413, "Photo must be no larger than 20 MiB")
    await to_thread.run_sync(metadata_call, settings, token, "/api/v1/local/validate", {})
    if not upload_lock.acquire(blocking=False):
        raise HTTPException(409, "Another upload is running; please retry shortly")
    stage = None
    try:
        target = media_directory(settings, claims)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".incoming-", dir=target.parent))
        digest = hashlib.sha256()
        count = 0
        with (stage / "original").open("xb") as output:
            async for chunk in request.stream():
                count += len(chunk)
                if count > claims["byte_size"] or count > MAX_BYTES:
                    raise HTTPException(413, "Photo exceeds its authorized size")
                await to_thread.run_sync(output.write, chunk)
                digest.update(chunk)
        if count != claims["byte_size"]:
            raise HTTPException(400, "Photo transfer was incomplete")
        fingerprint = {k: claims[k] for k in
                       ("sub", "media_id", "filename", "byte_size", "content_type")}
        if target.exists():
            manifest_file = target / "manifest.json"
            if manifest_file.is_symlink() or not manifest_file.is_file():
                raise HTTPException(409, "Existing upload needs manual recovery")
            manifest = json.loads(manifest_file.read_text("utf-8"))
            if manifest["upload"] != fingerprint or manifest["receipt"]["original_sha256"] != digest.hexdigest():
                raise HTTPException(409, "Upload ID already belongs to another file")
            receipt = manifest["receipt"]
        else:
            receipt = await to_thread.run_sync(process_photo, stage, claims, digest.hexdigest())
            (stage / "manifest.json").write_text(
                json.dumps({"upload": fingerprint, "receipt": receipt}), encoding="utf-8")
            os.rename(stage, target)
            stage = None
        # If this fails, final originals, thumbnail and manifest remain for an
        # identical retry. No rollback ever deletes a successfully saved photo.
        return await to_thread.run_sync(metadata_call, settings, token,
                                        "/api/v1/local/complete", receipt)
    finally:
        if stage is not None:
            # Only the temporary directory created by this request; never target.
            shutil.rmtree(stage)
        upload_lock.release()


@router.get("/objects/{media_id}/{kind}")
async def read_photo(media_id: UUID, kind: Literal["original", "thumbnail"],
                     request: Request, settings: Config) -> FileResponse:
    token, claims = authorization(request, settings, "read")
    if claims["media_id"] != str(media_id) or claims.get("kind") != kind:
        raise HTTPException(403, "Permission does not cover this file")
    await to_thread.run_sync(metadata_call, settings, token, "/api/v1/local/validate", {})
    target = media_directory(settings, claims)
    file = target / ("original" if kind == "original" else "thumbnail.jpg")
    manifest_file = target / "manifest.json"
    if file.is_symlink() or manifest_file.is_symlink():
        raise HTTPException(403, "Linked files are not allowed")
    if not file.is_file() or not manifest_file.is_file():
        raise HTTPException(404, "Photo is unavailable on this PC")
    manifest = json.loads(manifest_file.read_text("utf-8"))
    return FileResponse(file,
        media_type=manifest["upload"]["content_type"] if kind == "original" else "image/jpeg",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


app = create_app()
