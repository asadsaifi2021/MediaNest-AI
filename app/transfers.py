"""Short-lived, node-specific grants; never pass Supabase credentials to storage."""
import hashlib
import hmac
import time
from typing import Annotated, Literal
from uuid import UUID

import jwt
from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from .auth import CurrentUser
from .config import Settings, get_settings
from .storage import Database

router = APIRouter(prefix="/api/v1", tags=["transfers"])
Config = Annotated[Settings, Depends(get_settings)]
MAX_BYTES = 256 * 1024 * 1024
ISSUER = "medianest-transfer"


def secret(settings: Settings) -> str:
    if not settings.local_node_id or not settings.local_node_secret:
        raise HTTPException(503, "Local storage service needs server-side configuration")
    value = settings.local_node_secret.get_secret_value()
    if len(value) < 32:
        raise HTTPException(503, "Local storage secret must contain at least 32 characters")
    return value


def decode_grant(token: str, key: str, node_id: str) -> dict:
    try:
        claims = jwt.decode(token, key, algorithms=["HS256"], issuer=ISSUER, audience=node_id,
                            options={"require": ["exp", "iat", "sub", "media_id", "purpose"]})
        UUID(claims["sub"])
        UUID(claims["media_id"])
        return claims
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(401, "File permission is invalid or expired") from exc


def signed_grant(claims: dict, settings: Settings, lifetime: int) -> str:
    now = int(time.time())
    return jwt.encode({**claims, "iat": now, "exp": now + lifetime, "iss": ISSUER,
                       "aud": settings.local_node_id}, secret(settings), algorithm="HS256")


def active_node(client, node_id: str, owner: str) -> dict:
    rows = client.table("storage_nodes").select("*").eq("id", node_id).eq(
        "user_id", owner).limit(1).execute().data
    if not rows or rows[0]["disabled_at"]:
        raise HTTPException(404, "Active storage registration not found")
    return rows[0]


class UploadRequest(BaseModel):
    model_config = {"extra": "forbid"}
    media_id: UUID
    filename: str = Field(min_length=1, max_length=180)
    byte_size: int = Field(ge=1, le=MAX_BYTES)
    content_type: Literal["image/jpeg", "image/png", "image/webp", "video/mp4",
                          "video/webm", "video/quicktime", "audio/mpeg", "audio/mp4",
                          "audio/wav", "audio/x-wav", "audio/flac", "audio/ogg"]

    @field_validator("filename")
    @classmethod
    def filename_only(cls, value: str) -> str:
        if any(c in value for c in '/\\') or any(ord(c) < 32 for c in value):
            raise ValueError("Use a filename without a directory")
        return value


@router.post("/storage-nodes/{node_id}/upload-grant")
async def upload_grant(node_id: UUID, payload: UploadRequest, user: CurrentUser,
                       client: Database, settings: Config) -> dict:
    if payload.content_type.startswith("image/") and payload.byte_size > 20 * 1024 * 1024:
        raise HTTPException(413, "Photos are limited to 20 MiB")
    secret(settings)
    if str(node_id) != settings.local_node_id:
        raise HTTPException(409, "This storage node is not configured for uploads")
    node = await to_thread.run_sync(active_node, client, str(node_id), user["sub"])
    token = signed_grant({**payload.model_dump(mode="json"), "sub": user["sub"],
                          "purpose": "upload"}, settings, 900)
    return {"token": token, "url": node["base_url"] + "/upload", "expires_in": 900}


@router.post("/media/{media_id}/access-grant")
async def access_grant(media_id: UUID, user: CurrentUser, client: Database, settings: Config,
                       kind: Literal["original", "thumbnail", "playback"] = "thumbnail") -> dict:
    secret(settings)

    def lookup() -> tuple[dict, dict]:
        rows = client.table("media_objects").select("*").eq("media_id", str(media_id)).eq(
            "user_id", user["sub"]).eq("kind", kind).limit(1).execute().data
        if not rows:
            raise HTTPException(404, "Local file reference not found")
        obj = rows[0]
        if obj["storage_node_id"] != settings.local_node_id:
            raise HTTPException(409, "Storage node is not configured")
        return obj, active_node(client, obj["storage_node_id"], user["sub"])
    obj, node = await to_thread.run_sync(lookup)
    token = signed_grant({"sub": user["sub"], "media_id": str(media_id), "purpose": "read",
                          "kind": kind, "object_key": obj["object_key"]}, settings, 120)
    return {"token": token, "url": node["base_url"] + f"/objects/{media_id}/{kind}",
            "expires_in": 120}


async def node_request(request: Request, settings: Config) -> dict:
    key = secret(settings)
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    claims = decode_grant(token, key, settings.local_node_id)
    # The grant alone belongs in the browser. Completion/introspection also
    # requires proof from the storage service, bound to method, path and body.
    body = await request.body()
    data = (request.method + ":" + request.url.path + ":" + token + ":").encode() + body
    expected = hmac.new(key.encode(), data, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-Node-Signature", "")):
        raise HTTPException(401, "Storage service authentication failed")
    return claims


NodeClaims = Annotated[dict, Depends(node_request)]


@router.post("/local/validate")
async def validate_transfer(claims: NodeClaims, client: Database, settings: Config) -> dict:
    await to_thread.run_sync(active_node, client, settings.local_node_id, claims["sub"])
    if claims["purpose"] == "read":
        def lookup():
            if claims.get("kind") == "face":
                original = client.table("media_objects").select("id").eq(
                    "user_id", claims["sub"]).eq("storage_node_id", settings.local_node_id).eq(
                    "media_id", claims["media_id"]).eq("kind", "original").limit(1).execute().data
                if not original:
                    return []
                return client.table("face_embeddings").select("id").eq("user_id", claims["sub"]).eq(
                    "media_id", claims["media_id"]).eq("id", claims["object_key"]).limit(1).execute().data
            return client.table("media_objects").select("id").eq(
                "user_id", claims["sub"]).eq("storage_node_id", settings.local_node_id).eq(
                "media_id", claims["media_id"]).eq("kind", claims["kind"]).eq(
                "object_key", claims["object_key"]).limit(1).execute().data
        if not await to_thread.run_sync(lookup):
            raise HTTPException(404, "File access is no longer available")
    elif claims["purpose"] != "upload":
        raise HTTPException(403, "Wrong file permission")
    return {"status": "authorized"}


class Receipt(BaseModel):
    model_config = {"extra": "forbid"}
    original_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    thumbnail_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    thumbnail_size: int = Field(gt=0, le=2 * 1024 * 1024)
    playback_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    playback_size: int | None = Field(default=None, gt=0, le=1024 * 1024 * 1024)
    playback_type: Literal["video/mp4", "audio/mp4"] | None = None
    media_info: dict = Field(default_factory=dict)


@router.post("/local/complete")
async def complete_transfer(payload: Receipt, claims: NodeClaims, client: Database,
                            settings: Config) -> dict:
    if claims["purpose"] != "upload":
        raise HTTPException(403, "Upload permission required")
    await to_thread.run_sync(active_node, client, settings.local_node_id, claims["sub"])
    params = {"p_user_id": claims["sub"], "p_node_id": settings.local_node_id,
              "p_media_id": claims["media_id"], "p_filename": claims["filename"],
              "p_size": claims["byte_size"], "p_content_type": claims["content_type"],
              **{"p_" + k: v for k, v in payload.model_dump(exclude_none=True).items()
                 if k != "media_info"}}
    is_av = not claims["content_type"].startswith("image/")
    if is_av:
        if not all((payload.playback_sha256, payload.playback_size, payload.playback_type)):
            raise HTTPException(422, "Playback metadata required")
        params["p_info"] = payload.media_info
    else:
        params = {k: v for k, v in params.items() if not k.startswith("p_playback")}
    try:
        await to_thread.run_sync(lambda: client.rpc(
            "complete_media_upload" if is_av else "complete_photo_upload", params).execute())
    except Exception as exc:
        if getattr(exc, "code", "") in ("PGRST202", "42883"):
            raise HTTPException(503, "Apply Supabase migrations through 007 to enable media uploads") from exc
        raise HTTPException(502, "Metadata sync failed; local files are preserved. Retry upload.") from exc
    return {"media_id": claims["media_id"], "status": "complete"}
