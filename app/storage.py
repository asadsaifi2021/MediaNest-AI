"""Owner-scoped storage registry; does not fetch origins or grant file access."""

from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .auth import CurrentUser
from .database import SupabaseQueryClient
from .routes import get_supabase_client

router = APIRouter(prefix="/api/v1/storage-nodes", tags=["storage"])
Database = Annotated[SupabaseQueryClient, Depends(get_supabase_client)]
COLUMNS = "id,device_id,display_name,base_url,created_at,disabled_at"


class StorageNodeCreate(BaseModel):
    model_config = {"extra": "forbid"}

    device_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    display_name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=2048)

    @field_validator("display_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Storage name cannot be blank")
        return value.strip()

    @field_validator("base_url")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        value = value.strip()
        url = urlsplit(value)
        if (
            not url.hostname or url.username is not None or url.password is not None
            or url.query or url.fragment or url.path not in ("", "/")
            or any(c.isspace() or ord(c) < 32 for c in value)
            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in url.hostname)
        ):
            raise ValueError("Use a server origin without credentials, paths, or query strings")
        if url.scheme != "https" and not (
            url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1")
        ):
            raise ValueError("Use HTTPS, or HTTP on localhost for development")
        port = url.port  # validates invalid/out-of-range ports
        if port == 0:
            raise ValueError("Port must be between 1 and 65535")
        return f"{url.scheme}://{url.hostname}" + (f":{port}" if port else "")


class StorageNode(StorageNodeCreate):
    id: UUID
    created_at: datetime
    disabled_at: datetime | None = None


def storage_error(exc: Exception) -> HTTPException:
    if getattr(exc, "code", None) in {"42P01", "PGRST205"}:
        return HTTPException(503, "Storage registry needs Supabase migration 004")
    if getattr(exc, "code", None) == "23505":
        return HTTPException(409, "That device ID is already registered; choose another ID")
    return HTTPException(502, "Storage registry request failed")


@router.get("", response_model=list[StorageNode])
async def list_nodes(
    user: CurrentUser, client: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    def execute() -> list[dict]:
        return (
            client.table("storage_nodes").select(COLUMNS).eq("user_id", user["sub"])
            .order("created_at", desc=True).order("id")
            .range(offset, offset + limit - 1).execute().data
        )
    try:
        return await to_thread.run_sync(execute)
    except Exception as exc:
        raise storage_error(exc) from exc


@router.post("", response_model=StorageNode, status_code=201)
async def register_node(payload: StorageNodeCreate, user: CurrentUser, client: Database) -> dict:
    record = {**payload.model_dump(), "user_id": user["sub"]}

    def execute() -> dict:
        result = client.table("storage_nodes").insert(record).execute().data[0]
        return {key: result[key] for key in COLUMNS.split(",")}
    try:
        return await to_thread.run_sync(execute)
    except Exception as exc:
        raise storage_error(exc) from exc


@router.post("/{node_id}/disable", response_model=StorageNode)
async def disable_node(node_id: UUID, user: CurrentUser, client: Database) -> dict:
    # Soft-disable preserves file references; it never deletes NAS files.
    def execute() -> list[dict]:
        return (
            client.table("storage_nodes")
            .update({"disabled_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", str(node_id)).eq("user_id", user["sub"]).execute().data
        )
    try:
        rows = await to_thread.run_sync(execute)
    except Exception as exc:
        raise storage_error(exc) from exc
    if not rows:
        raise HTTPException(404, "Storage node not found")
    return {key: rows[0][key] for key in COLUMNS.split(",")}
