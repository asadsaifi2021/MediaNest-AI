"""Owner-requested local AI indexing; node credentials never enter the browser."""
import json
from typing import Annotated
from uuid import UUID, uuid4

from anyio import to_thread
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .auth import CurrentUser
from .routes import FaceEmbeddingIngest, TagUpdate
from .storage import Database
from .transfers import (
    Config,
    NodeClaims,
    Receipt,
    UploadRequest,
    active_node,
    complete_transfer,
    signed_grant,
)

router = APIRouter(prefix="/api/v1", tags=["indexing"])


class IndexOptions(BaseModel):
    model_config = {"extra": "forbid"}
    objects: bool = True
    transcription: bool = True
    faces: bool = False


async def worker_node(claims: dict, client, settings) -> dict:
    if claims.get("purpose") != "worker" or claims["sub"] != settings.local_node_id:
        raise HTTPException(403, "Worker permission required")
    def lookup():
        return client.table("storage_nodes").select("*").eq(
            "id", settings.local_node_id).limit(1).execute().data
    rows = await to_thread.run_sync(lookup)
    if not rows or rows[0]["disabled_at"]:
        raise HTTPException(403, "Storage node is disabled or missing")
    return rows[0]


@router.post("/media/{media_id}/index")
async def request_index(media_id: UUID, payload: IndexOptions, user: CurrentUser,
                        client: Database, settings: Config):
    if not any(payload.model_dump().values()):
        raise HTTPException(422, "Choose at least one processing option")
    def lookup():
        return client.table("media_objects").select("*").eq("media_id", str(media_id)).eq(
            "user_id", user["sub"]).eq("kind", "original").limit(1).execute().data
    objects = await to_thread.run_sync(lookup)
    if not objects or objects[0]["storage_node_id"] != settings.local_node_id:
        raise HTTPException(404, "Configured local original not found")
    await to_thread.run_sync(active_node, client, settings.local_node_id, user["sub"])
    values = {"ai_status": "queued", "ai_request_id": str(uuid4()),
              "ai_options": payload.model_dump(), "ai_message": None}
    await to_thread.run_sync(lambda: client.table("media_metadata").update(values).eq(
        "id", str(media_id)).eq("user_id", user["sub"]).execute())
    return values


@router.post("/local/tasks")
async def local_tasks(claims: NodeClaims, client: Database, settings: Config):
    node = await worker_node(claims, client, settings)
    rows = await to_thread.run_sync(lambda: client.table("media_metadata").select(
        "id,user_id,file_type,ai_request_id,ai_options").eq("user_id", node["user_id"]).eq(
        "device_id", node["device_id"]).eq("ai_status", "queued").order("updated_at").limit(100).execute().data)
    return {"tasks": rows, "owner": node["user_id"]}


class FaceResult(FaceEmbeddingIngest):
    id: UUID


class IndexResult(BaseModel):
    model_config = {"extra": "forbid"}
    media_id: UUID
    request_id: UUID
    tags: list[str] | None = Field(default=None, max_length=50)
    transcription: str | None = Field(default=None, max_length=200000)
    faces: list[FaceResult] | None = Field(default=None, max_length=100)
    models: dict[str, str] = Field(default_factory=dict, max_length=10)
    error: str | None = Field(default=None, max_length=200)


@router.post("/local/index-result")
async def index_result(payload: IndexResult, claims: NodeClaims, client: Database, settings: Config):
    node = await worker_node(claims, client, settings)
    if payload.tags is not None:
        payload.tags = TagUpdate(tags=payload.tags).tags
    if len(json.dumps(payload.models)) > 4096:
        raise HTTPException(422, "Model metadata too large")
    result = await to_thread.run_sync(lambda: client.rpc("apply_index_result", {
        "p_owner": node["user_id"], "p_node": node["id"], "p_media": str(payload.media_id),
        "p_request": str(payload.request_id), "p_result": payload.model_dump(mode="json"),
    }).execute().data)
    return {"status": "applied" if result else "superseded"}


class Recovery(BaseModel):
    upload: UploadRequest
    receipt: Receipt


class TaskIdentity(BaseModel):
    media_id: UUID
    request_id: UUID


@router.post("/local/task-current")
async def task_current(payload: TaskIdentity, claims: NodeClaims, client: Database, settings: Config):
    node = await worker_node(claims, client, settings)
    rows = await to_thread.run_sync(lambda: client.table("media_metadata").select("id").eq(
        "id", str(payload.media_id)).eq("user_id", node["user_id"]).eq(
        "device_id", node["device_id"]).eq("ai_request_id", str(payload.request_id)).eq(
        "ai_status", "queued").limit(1).execute().data)
    return {"current": bool(rows)}


@router.post("/local/recover")
async def recover_upload(payload: Recovery, claims: NodeClaims, client: Database, settings: Config):
    node = await worker_node(claims, client, settings)
    upload = {**payload.upload.model_dump(mode="json"), "sub": node["user_id"], "purpose": "upload"}
    return await complete_transfer(payload.receipt, upload, client, settings)


@router.get("/faces")
async def list_faces(user: CurrentUser, client: Database,
                     offset: Annotated[int, Query(ge=0)] = 0,
                     person_name: Annotated[str | None, Query(max_length=200)] = None):
    def query():
        query = client.table("face_embeddings").select(
            "id,media_id,person_name,model_id,vector_version").eq("user_id", user["sub"])
        if person_name is not None:
            query = query.eq("person_name", person_name)
        return query.order("id").range(offset, offset + 49).execute().data
    return await to_thread.run_sync(query)


@router.get("/face-groups")
async def face_groups(user: CurrentUser, client: Database):
    return await to_thread.run_sync(lambda: client.rpc(
        "named_face_groups", {"p_owner": user["sub"]}).execute().data)


@router.post("/faces/{face_id}/similar")
async def similar_faces(face_id: UUID, user: CurrentUser, client: Database,
                        threshold: Annotated[float, Query(ge=0, le=1)] = 0.6):
    def query():
        rows = client.table("face_embeddings").select("*").eq("id", str(face_id)).eq(
            "user_id", user["sub"]).limit(1).execute().data
        if not rows:
            raise HTTPException(404, "Face not found")
        face = rows[0]
        return client.rpc("match_faces_v2", {"query_embedding": face["embedding"],
            "p_user_id": user["sub"], "p_model_id": face["model_id"],
            "p_vector_version": face["vector_version"], "match_threshold": threshold,
            "match_count": 100}).execute().data
    return {"matches": await to_thread.run_sync(query)}


@router.post("/faces/{face_id}/preview-grant")
async def face_preview_grant(face_id: UUID, user: CurrentUser, client: Database, settings: Config):
    def lookup():
        faces = client.table("face_embeddings").select("media_id").eq(
            "id", str(face_id)).eq("user_id", user["sub"]).limit(1).execute().data
        if not faces:
            raise HTTPException(404, "Face not found")
        media = faces[0]["media_id"]
        objects = client.table("media_objects").select("id").eq("media_id", media).eq(
            "user_id", user["sub"]).eq("storage_node_id", settings.local_node_id).eq(
            "kind", "original").limit(1).execute().data
        if not objects:
            raise HTTPException(404, "Local face preview not found")
        return media, active_node(client, settings.local_node_id, user["sub"])
    media, node = await to_thread.run_sync(lookup)
    token = signed_grant({"sub": user["sub"], "media_id": media, "purpose": "read",
        "kind": "face", "object_key": str(face_id)}, settings, 120)
    return {"token": token, "url": node["base_url"] + f"/faces/{media}/{face_id}"}


class NameFaces(BaseModel):
    model_config = {"extra": "forbid"}
    ids: list[UUID] = Field(min_length=1, max_length=100)
    name: str = Field(max_length=200)


@router.post("/faces/name")
async def name_faces(payload: NameFaces, user: CurrentUser, client: Database):
    rows = await to_thread.run_sync(lambda: client.table("face_embeddings").update(
        {"person_name": payload.name.strip() or None}).eq("user_id", user["sub"]).in_(
            "id", [str(i) for i in payload.ids]).execute().data)
    return {"updated": len(rows)}


@router.post("/media/{media_id}/forget-faces")
async def forget_faces(media_id: UUID, user: CurrentUser, client: Database):
    # Atomic invalidation also prevents an in-flight worker restoring erased embeddings.
    await to_thread.run_sync(lambda: client.rpc("forget_media_faces", {
        "p_owner": user["sub"], "p_media": str(media_id)}).execute())
    return {"status": "removed"}
