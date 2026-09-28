"""HTTP routes for cloud archive coordination and media search."""

import logging
import math
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from .auth import CurrentUser, verify_edge_signature
from .config import Settings, get_settings
from .database import (
    InvalidSupabaseKey,
    SupabaseQueryClient,
    create_data_api_client,
    database_error_detail,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class ArchiveEventCreate(BaseModel):
    asset_id: UUID
    event_type: Literal["discovered", "indexed", "uploaded", "deleted", "failed"]
    device_id: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArchiveEvent(ArchiveEventCreate):
    id: UUID
    user_id: str
    created_at: datetime


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    environment: str


class DatabaseHealthResponse(BaseModel):
    status: Literal["connected"] = "connected"
    database: Literal["supabase"] = "supabase"


class FaceEmbeddingIngest(BaseModel):
    model_config = {"extra": "forbid"}

    model_id: str = Field(default="legacy-512", min_length=1, max_length=128)
    person_name: str | None = Field(default=None, max_length=200)
    embedding: list[float]
    vector_version: int = Field(default=1, ge=1)

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: list[float]) -> list[float]:
        if len(value) != 512:
            raise ValueError("embedding must contain exactly 512 values")
        if not all(math.isfinite(component) for component in value):
            raise ValueError("embedding values must be finite")
        if not any(component != 0 for component in value):
            raise ValueError("embedding must not be a zero vector")
        return value


class MediaSyncRequest(BaseModel):
    model_config = {"extra": "forbid"}

    device_id: str = Field(min_length=1, max_length=128)
    local_file_id: str = Field(min_length=1, max_length=512)
    file_type: Literal["image", "video", "audio"]
    thumbnail_url: AnyHttpUrl | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    transcription: str | None = Field(default=None, max_length=200_000)
    faces: list[FaceEmbeddingIngest] = Field(default_factory=list, max_length=100)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in value:
            clean = tag.strip()
            if not clean or len(clean) > 100:
                raise ValueError("tags must contain 1 to 100 characters")
            key = clean.casefold()
            if key not in seen:
                normalized.append(clean)
                seen.add(key)
        return normalized


class MediaSyncResponse(BaseModel):
    status: Literal["success"] = "success"
    media_id: UUID


class VectorSearchRequest(BaseModel):
    model_config = {"extra": "forbid"}

    embedding: list[float]
    model_id: str = Field(default="legacy-512", min_length=1, max_length=128)
    vector_version: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: list[float]) -> list[float]:
        return FaceEmbeddingIngest.validate_embedding(value)


class MediaRecord(BaseModel):
    model_config = {"extra": "allow"}

    id: UUID
    user_id: str
    device_id: str
    local_file_id: str
    file_type: str
    thumbnail_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    transcription: str | None = None
    created_at: datetime
    updated_at: datetime


class MediaSearchResponse(BaseModel):
    results: list[MediaRecord]


class MediaPage(MediaSearchResponse):
    has_more: bool


class FaceMatch(BaseModel):
    model_config = {"extra": "allow"}

    media_id: UUID
    face_id: UUID
    person_name: str | None = None
    similarity: float


class FaceSearchResponse(BaseModel):
    matches: list[FaceMatch]


async def get_supabase_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SupabaseQueryClient:
    if settings.supabase_url is None or settings.supabase_secret_key is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    try:
        return await to_thread.run_sync(
            create_data_api_client,
            str(settings.supabase_url).rstrip("/"),
            settings.supabase_secret_key.get_secret_value(),
        )
    except InvalidSupabaseKey as exc:
        logger.error("Invalid Supabase server key configuration: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(service=settings.app_name, environment=settings.app_environment)


@router.get("/db-health", response_model=DatabaseHealthResponse, tags=["system"])
async def database_health(
    client: Annotated[SupabaseQueryClient, Depends(get_supabase_client)],
) -> DatabaseHealthResponse:
    """Check that the configured Supabase Data API can answer a small query."""

    def check_connection() -> None:
        client.table("media_metadata").select("id,ai_tags,media_info,ai_request_id").limit(1).execute()
        client.table("archive_events").select("id").limit(1).execute()
        client.table("face_embeddings").select("id,model_id").limit(1).execute()
        client.rpc("match_faces_v2", {
            "query_embedding": [1.0] + [0.0] * 511,
            "match_threshold": 1.0, "match_count": 1,
            "p_user_id": "00000000-0000-0000-0000-000000000000",
        }).execute()

    try:
        await to_thread.run_sync(check_connection)
    except Exception as exc:
        logger.exception("Supabase database health check failed")
        raise HTTPException(status_code=503, detail=database_error_detail(exc)) from exc
    return DatabaseHealthResponse()


@router.get("/api/v1/archive-events", response_model=list[ArchiveEvent], tags=["archive"])
async def list_archive_events(
    user: CurrentUser,
    client: Annotated[SupabaseQueryClient, Depends(get_supabase_client)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, Any]]:
    def query() -> list[dict[str, Any]]:
        response = (
            client.table("archive_events").select("*").eq("user_id", user["sub"])
            .order("occurred_at", desc=True).limit(limit).execute()
        )
        return response.data

    try:
        return await to_thread.run_sync(query)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Archive database request failed") from exc


@router.post(
    "/api/v1/archive-events",
    response_model=ArchiveEvent,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_edge_signature)],
    tags=["archive"],
)
async def create_archive_event(
    event: ArchiveEventCreate,
    user: CurrentUser,
    client: Annotated[SupabaseQueryClient, Depends(get_supabase_client)],
) -> dict[str, Any]:
    record = {
        **event.model_dump(mode="json"),
        "id": str(uuid4()),
        "user_id": user["sub"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    def insert() -> dict[str, Any]:
        response = client.table("archive_events").insert(record).execute()
        if not response.data:
            raise RuntimeError("Supabase returned no inserted record")
        return response.data[0]

    try:
        return await to_thread.run_sync(insert)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Archive database request failed") from exc


@router.post(
    "/api/v1/media/sync",
    response_model=MediaSyncResponse,
    dependencies=[Depends(verify_edge_signature)],
    tags=["media"],
)
async def sync_media(
    payload: MediaSyncRequest,
    user: CurrentUser,
    client: Annotated[SupabaseQueryClient, Depends(get_supabase_client)],
) -> MediaSyncResponse:
    """Atomically upsert media metadata and replace its face embeddings."""

    params = {
        "p_user_id": user["sub"],
        "p_device_id": payload.device_id,
        "p_local_file_id": payload.local_file_id,
        "p_file_type": payload.file_type,
        "p_thumbnail_url": str(payload.thumbnail_url) if payload.thumbnail_url else None,
        "p_tags": payload.tags,
        "p_transcription": payload.transcription,
        "p_faces": [face.model_dump(mode="json") for face in payload.faces],
    }

    def execute() -> Any:
        return client.rpc("sync_media_metadata", params).execute().data

    try:
        data = await to_thread.run_sync(execute)
        media_id = data[0]["media_id"] if isinstance(data, list) else data
        return MediaSyncResponse(media_id=media_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Media synchronization failed") from exc


@router.get(
    "/api/v1/media/search",
    response_model=MediaSearchResponse,
    tags=["media"],
)
async def search_media_by_tag(
    user: CurrentUser,
    client: Annotated[SupabaseQueryClient, Depends(get_supabase_client)],
    tag: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MediaSearchResponse:
    clean_tag = tag.strip()
    if not clean_tag:
        raise HTTPException(status_code=422, detail="Tag cannot be blank")

    def execute() -> list[dict[str, Any]]:
        response = (
            client.table("media_metadata")
            .select("*")
            .eq("user_id", user["sub"])
            .contains("tags", [clean_tag])
            .order("updated_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return response.data

    try:
        return MediaSearchResponse(results=await to_thread.run_sync(execute))
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Media search failed") from exc


@router.post(
    "/api/v1/media/search-face",
    response_model=FaceSearchResponse,
    tags=["media"],
)
async def search_media_by_face(
    query: VectorSearchRequest,
    user: CurrentUser,
    client: Annotated[SupabaseQueryClient, Depends(get_supabase_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FaceSearchResponse:
    params = {
        "query_embedding": query.embedding,
        "match_threshold": (
            query.threshold if query.threshold is not None else settings.face_match_threshold
        ),
        "match_count": query.limit,
        "p_user_id": user["sub"],
        "p_model_id": query.model_id,
        "p_vector_version": query.vector_version,
    }

    def execute() -> list[dict[str, Any]]:
        return client.rpc("match_faces_v2", params).execute().data

    try:
        return FaceSearchResponse(matches=await to_thread.run_sync(execute))
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Face search failed") from exc


@router.get("/api/v1/media", response_model=MediaPage, tags=["media"])
async def list_media(
    user: CurrentUser,
    client: Annotated[SupabaseQueryClient, Depends(get_supabase_client)],
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
    file_type: Literal["image", "video", "audio"] | None = None,
    tag: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort: Literal["newest", "oldest"] = "newest",
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> MediaPage:
    if tag is not None and not tag.strip():
        raise HTTPException(status_code=422, detail="Tag cannot be blank")

    def execute() -> list[dict[str, Any]]:
        if q and q.strip():
            return client.rpc("search_archive", {
                "p_owner": user["sub"], "p_query": q.strip(),
                "p_type": file_type, "p_tag": tag.strip() if tag else None,
                "p_oldest": sort == "oldest", "p_offset": offset, "p_limit": limit + 1,
            }).execute().data
        query = client.table("media_metadata").select("*").eq("user_id", user["sub"])
        if file_type:
            query = query.eq("file_type", file_type)
        if tag:
            query = query.contains("tags", [tag.strip()])
        return (
            query.order("created_at", desc=sort == "newest")
            .order("id", desc=sort == "newest")
            .range(offset, offset + limit).execute().data
        )

    try:
        rows = await to_thread.run_sync(execute)
        return MediaPage(results=rows[:limit], has_more=len(rows) > limit)
    except Exception as exc:
        if getattr(exc, "code", "") in {"PGRST202", "PGRST204", "42703", "42883"}:
            raise HTTPException(503, "Apply Supabase migrations 006–008 to enable archive search and indexing") from exc
        raise HTTPException(status_code=502, detail="Media library request failed") from exc


@router.get("/api/v1/media/{media_id}", response_model=MediaRecord, tags=["media"])
async def get_media(
    media_id: UUID,
    user: CurrentUser,
    client: Annotated[SupabaseQueryClient, Depends(get_supabase_client)],
) -> MediaRecord:
    def execute() -> list[dict[str, Any]]:
        return (
            client.table("media_metadata").select("*")
            .eq("user_id", user["sub"]).eq("id", str(media_id)).limit(1).execute().data
        )

    try:
        rows = await to_thread.run_sync(execute)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Media detail request failed") from exc
    if not rows:
        raise HTTPException(status_code=404, detail="Media not found")
    return MediaRecord(**rows[0])


class TagUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    tags: list[str] = Field(max_length=50)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        return MediaSyncRequest.normalize_tags(value)


@router.post("/api/v1/media/{media_id}/tags", response_model=MediaRecord)
async def update_tags(media_id: UUID, payload: TagUpdate, user: CurrentUser,
                      client: Annotated[SupabaseQueryClient, Depends(get_supabase_client)]):
    def execute():
        return client.table("media_metadata").update({"tags": payload.tags}).eq(
            "id", str(media_id)).eq("user_id", user["sub"]).execute().data
    try:
        rows = await to_thread.run_sync(execute)
    except Exception as exc:
        raise HTTPException(502, "Could not save tags") from exc
    if not rows:
        raise HTTPException(404, "Media not found")
    return rows[0]
