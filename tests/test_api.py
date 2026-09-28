from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.main import app
from app.routes import get_supabase_client

TEST_SECRET = "test-edge-secret"
TEST_ISSUER = "https://project.supabase.co/auth/v1"


@pytest.mark.anyio
async def test_storage_registration_is_owner_scoped(client, private_key):
    from app.storage import COLUMNS

    records = []

    class NodeQuery(FakeQuery):
        changes = None

        def update(self, changes):
            self.changes = changes
            return self

        def execute(self):
            if self.inserted:
                records.append({
                    **self.inserted, "id": str(uuid4()), "created_at": "2026-09-27T00:00:00Z",
                    "disabled_at": None,
                })
                return SimpleNamespace(data=[records[-1]])
            rows = [r for r in records if all(r[k] == v for k, v in self.filters)]
            if self.changes:
                for row in rows:
                    row.update(self.changes)
            return SimpleNamespace(data=[{k: r[k] for k in COLUMNS.split(",")} for r in rows])

    class Nodes:
        def table(self, name):
            assert name == "storage_nodes"
            return NodeQuery([])

    app.dependency_overrides[get_supabase_client] = lambda: Nodes()
    alice = {"Authorization": f"Bearer {make_token(private_key, subject='alice')}"}
    bob = {"Authorization": f"Bearer {make_token(private_key, subject='bob')}"}
    payload = {
        "device_id": "windows-pc", "display_name": " My PC ",
        "base_url": "http://127.0.0.1:8100/",
    }
    assert (await client.post("/api/v1/storage-nodes", json=payload)).status_code == 401
    created = await client.post("/api/v1/storage-nodes", headers=alice, json=payload)
    assert created.status_code == 201
    assert created.json()["display_name"] == "My PC"
    assert created.json()["base_url"] == "http://127.0.0.1:8100"
    assert records[0]["user_id"] == "alice"
    assert "user_id" not in created.json()
    assert len((await client.get("/api/v1/storage-nodes", headers=alice)).json()) == 1
    assert (await client.get("/api/v1/storage-nodes", headers=bob)).json() == []
    endpoint = f"/api/v1/storage-nodes/{created.json()['id']}/disable"
    assert (await client.post(endpoint, headers=bob)).status_code == 404
    assert records[0]["disabled_at"] is None
    assert (await client.post(endpoint, headers=alice)).status_code == 200
    assert records[0]["disabled_at"] is not None
    assert len(records) == 1
    assert (await client.post(
        "/api/v1/storage-nodes", headers=alice, json={**payload, "user_id": "bob"}
    )).status_code == 422


@pytest.mark.parametrize("origin", [
    "file:///C:/photos", "http://192.168.1.10:8100", "https://user:password@nas.test",
    "https://nas.test/files", "https://nas.test?token=secret", "https://nas.test/#secret",
    "https://nas.test:99999", "https://nas.test:0", "https://nas.test\\evil",
])
def test_storage_origins_reject_unsafe_values(origin):
    from pydantic import ValidationError

    from app.storage import StorageNodeCreate

    with pytest.raises(ValidationError):
        StorageNodeCreate(device_id="pc", display_name="PC", base_url=origin)


@pytest.mark.anyio
async def test_storage_missing_migration_is_actionable(client, private_key):
    class MissingTable(RuntimeError):
        code = "PGRST205"

    class MissingRegistry:
        def table(self, name):
            raise MissingTable()

    app.dependency_overrides[get_supabase_client] = lambda: MissingRegistry()
    headers = {"Authorization": f"Bearer {make_token(private_key)}"}
    result = await client.get("/api/v1/storage-nodes", headers=headers)
    assert result.status_code == 503
    assert "migration 004" in result.json()["detail"]


class FakeQuery:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.inserted: dict[str, Any] | None = None
        self.filters: list[tuple[str, Any]] = []

    def select(self, *_: Any, **__: Any) -> FakeQuery:
        return self

    def eq(self, column: str, value: Any) -> FakeQuery:
        self.filters.append((column, value))
        return self

    def contains(self, column: str, value: Any) -> FakeQuery:
        self.filters.append((column, value))
        return self

    def order(self, *_: Any, **__: Any) -> FakeQuery:
        return self

    def limit(self, *_: Any, **__: Any) -> FakeQuery:
        return self

    def range(self, *_: Any, **__: Any) -> FakeQuery:
        return self

    def insert(self, record: dict[str, Any]) -> FakeQuery:
        self.inserted = record
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=[self.inserted] if self.inserted else self.rows)


class FakeSupabase:
    def __init__(self) -> None:
        self.query = FakeQuery([])
        self.rpc_calls: list[tuple[str, dict[str, Any]]] = []

    def table(self, _: str) -> FakeQuery:
        return self.query

    def rpc(self, name: str, params: dict[str, Any]) -> FakeRpc:
        self.rpc_calls.append((name, params))
        result: Any = str(uuid4()) if name == "sync_media_metadata" else []
        return FakeRpc(result)


class FakeRpc:
    def __init__(self, data: Any) -> None:
        self.data = data

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self.data)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def overrides(monkeypatch: pytest.MonkeyPatch, private_key: rsa.RSAPrivateKey):
    settings = Settings(
        supabase_url="https://project.supabase.co",
        supabase_secret_key="sb_secret_test",
        edge_hmac_secret=TEST_SECRET,
        supabase_jwt_issuer=TEST_ISSUER,
    )
    fake_db = FakeSupabase()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_supabase_client] = lambda: fake_db

    signing_key = SimpleNamespace(key=private_key.public_key())
    jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _: signing_key)
    monkeypatch.setattr("app.auth.get_jwks_client", lambda _: jwks)
    yield fake_db
    app.dependency_overrides.clear()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value


def make_token(
    private_key: rsa.RSAPrivateKey, *, expired: bool = False, subject: str = "user-123"
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": subject,
            "aud": "authenticated",
            "iss": TEST_ISSUER,
            "iat": now,
            "exp": now - timedelta(seconds=1) if expired else now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def make_hs256_token() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "user-123",
            "aud": "authenticated",
            "iss": TEST_ISSUER,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        "shared-secret-used-only-by-the-test",
        algorithm="HS256",
    )


def signed_headers(body: bytes, token: str, *, timestamp: int | None = None) -> dict[str, str]:
    signed_at = timestamp if timestamp is not None else int(time.time())
    digest = hmac.new(
        TEST_SECRET.encode(), f"{signed_at}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Edge-Timestamp": str(signed_at),
        "X-Edge-Signature": f"sha256={digest}",
    }


@pytest.mark.anyio
async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "MediaNest AI",
        "environment": "development",
    }


@pytest.mark.anyio
async def test_database_health(client: AsyncClient):
    response = await client.get("/db-health")
    assert response.status_code == 200
    assert response.json() == {"status": "connected", "database": "supabase"}


@pytest.mark.anyio
async def test_database_health_sanitizes_failures(client: AsyncClient):
    class FailingQuery(FakeQuery):
        def execute(self) -> SimpleNamespace:
            raise RuntimeError("sensitive database error")

    class FailingSupabase(FakeSupabase):
        def __init__(self) -> None:
            super().__init__()
            self.query = FailingQuery([])

    original_override = app.dependency_overrides[get_supabase_client]
    app.dependency_overrides[get_supabase_client] = lambda: FailingSupabase()
    try:
        response = await client.get("/db-health")
    finally:
        app.dependency_overrides[get_supabase_client] = original_override

    assert response.status_code == 503
    assert response.json() == {"detail": "Database connection unavailable"}


@pytest.mark.anyio
async def test_database_health_identifies_missing_migrations(client: AsyncClient):
    class MissingTableError(RuntimeError):
        code = "PGRST205"
        message = "Could not find the table public.media_metadata in the schema cache"

    class MissingTableQuery(FakeQuery):
        def execute(self) -> SimpleNamespace:
            raise MissingTableError()

    class MissingTableSupabase(FakeSupabase):
        def __init__(self) -> None:
            super().__init__()
            self.query = MissingTableQuery([])

    original_override = app.dependency_overrides[get_supabase_client]
    app.dependency_overrides[get_supabase_client] = lambda: MissingTableSupabase()
    try:
        response = await client.get("/db-health")
    finally:
        app.dependency_overrides[get_supabase_client] = original_override

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Database schema is not initialized; run the Supabase migrations"
    }


@pytest.mark.anyio
async def test_missing_bearer_token_is_rejected(client: AsyncClient):
    response = await client.get("/api/v1/archive-events")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


@pytest.mark.anyio
async def test_expired_jwt_is_rejected(client: AsyncClient, private_key: rsa.RSAPrivateKey):
    response = await client.get(
        "/api/v1/archive-events",
        headers={"Authorization": f"Bearer {make_token(private_key, expired=True)}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Token has expired"


@pytest.mark.anyio
async def test_mocked_jwks_verifies_valid_jwt(client: AsyncClient, private_key: rsa.RSAPrivateKey):
    response = await client.get(
        "/api/v1/archive-events",
        headers={"Authorization": f"Bearer {make_token(private_key)}"},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_hs256_token_is_validated_by_supabase_auth(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    class AuthResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, str]:
            return {"id": "user-123"}

    captured_headers: dict[str, str] = {}

    def fake_get(_: str, *, headers: dict[str, str], timeout: float) -> AuthResponse:
        del timeout
        captured_headers.update(headers)
        return AuthResponse()

    monkeypatch.setattr("app.auth.httpx.get", fake_get)
    token = make_hs256_token()
    response = await client.get(
        "/api/v1/archive-events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert captured_headers["apikey"] == "sb_secret_test"
    assert captured_headers["Authorization"] == f"Bearer {token}"


@pytest.mark.anyio
async def test_valid_hmac_preserves_body(client: AsyncClient, private_key: rsa.RSAPrivateKey):
    payload = {
        "asset_id": str(uuid4()),
        "event_type": "indexed",
        "device_id": "edge-1",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {"path": "photos/example.jpg"},
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    response = await client.post(
        "/api/v1/archive-events",
        content=body,
        headers=signed_headers(body, make_token(private_key)),
    )
    assert response.status_code == 201
    assert response.json()["asset_id"] == payload["asset_id"]
    assert response.json()["metadata"] == payload["metadata"]


@pytest.mark.anyio
async def test_invalid_hmac_is_rejected(client: AsyncClient, private_key: rsa.RSAPrivateKey):
    body = b"{}"
    headers = signed_headers(body, make_token(private_key))
    headers["X-Edge-Signature"] = "sha256=" + ("0" * 64)
    response = await client.post("/api/v1/archive-events", content=body, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid edge signature"


@pytest.mark.anyio
async def test_stale_hmac_is_rejected(client: AsyncClient, private_key: rsa.RSAPrivateKey):
    body = b"{}"
    response = await client.post(
        "/api/v1/archive-events",
        content=body,
        headers=signed_headers(body, make_token(private_key), timestamp=int(time.time()) - 301),
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Edge signature has expired"


@pytest.mark.anyio
async def test_sync_media_uses_authenticated_user(
    client: AsyncClient,
    private_key: rsa.RSAPrivateKey,
    overrides: FakeSupabase,
):
    payload = {
        "device_id": "edge-1",
        "local_file_id": "local-42",
        "file_type": "image",
        "tags": ["Family", " family "],
        "faces": [{"embedding": [0.01] * 512}],
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    response = await client.post(
        "/api/v1/media/sync",
        content=body,
        headers=signed_headers(body, make_token(private_key)),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    rpc_name, params = overrides.rpc_calls[-1]
    assert rpc_name == "sync_media_metadata"
    assert params["p_user_id"] == "user-123"
    assert params["p_tags"] == ["Family"]


@pytest.mark.anyio
async def test_sync_media_requires_edge_signature(
    client: AsyncClient, private_key: rsa.RSAPrivateKey
):
    response = await client.post(
        "/api/v1/media/sync",
        json={
            "device_id": "edge-1",
            "local_file_id": "local-42",
            "file_type": "image",
        },
        headers={"Authorization": f"Bearer {make_token(private_key)}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing edge signature headers"


@pytest.mark.anyio
async def test_sync_media_rejects_spoofed_user_id(
    client: AsyncClient, private_key: rsa.RSAPrivateKey
):
    payload = {
        "user_id": "victim-user",
        "device_id": "edge-1",
        "local_file_id": "local-42",
        "file_type": "image",
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    response = await client.post(
        "/api/v1/media/sync",
        content=body,
        headers=signed_headers(body, make_token(private_key)),
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_sync_media_rejects_wrong_embedding_size(
    client: AsyncClient, private_key: rsa.RSAPrivateKey
):
    payload = {
        "device_id": "edge-1",
        "local_file_id": "local-42",
        "file_type": "image",
        "faces": [{"embedding": [0.01] * 511}],
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    response = await client.post(
        "/api/v1/media/sync",
        content=body,
        headers=signed_headers(body, make_token(private_key)),
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_face_search_scopes_rpc_to_authenticated_user(
    client: AsyncClient,
    private_key: rsa.RSAPrivateKey,
    overrides: FakeSupabase,
):
    response = await client.post(
        "/api/v1/media/search-face",
        json={"embedding": [0.01] * 512, "limit": 5},
        headers={"Authorization": f"Bearer {make_token(private_key)}"},
    )
    assert response.status_code == 200
    rpc_name, params = overrides.rpc_calls[-1]
    assert rpc_name == "match_faces_v2"
    assert params["p_model_id"] == "legacy-512"
    assert params["p_vector_version"] == 1
    assert params["p_user_id"] == "user-123"
    assert params["match_count"] == 5


@pytest.mark.anyio
async def test_face_search_validates_vector_and_passes_model(
    client: AsyncClient, private_key: rsa.RSAPrivateKey, overrides: FakeSupabase
):
    headers = {"Authorization": f"Bearer {make_token(private_key)}"}
    response = await client.post("/api/v1/media/search-face", headers=headers, json={
        "embedding": [0.0] * 512,
    })
    assert response.status_code == 422
    response = await client.post("/api/v1/media/search-face", headers=headers, json={
        "embedding": [0.01] * 512, "model_id": "chosen-model", "vector_version": 2,
    })
    assert response.status_code == 200
    assert overrides.rpc_calls[-1][1]["p_model_id"] == "chosen-model"
    assert overrides.rpc_calls[-1][1]["p_vector_version"] == 2


@pytest.mark.anyio
async def test_readiness_requires_latest_search_function(client: AsyncClient):
    class MissingFunctionError(RuntimeError):
        code = "PGRST202"

    class OldSchema(FakeSupabase):
        def rpc(self, name: str, params: dict[str, Any]) -> FakeRpc:
            raise MissingFunctionError()

    app.dependency_overrides[get_supabase_client] = lambda: OldSchema()
    response = await client.get("/db-health")
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Database schema is not initialized; run the Supabase migrations"
    )


@pytest.mark.anyio
async def test_tag_search_filters_authenticated_user(
    client: AsyncClient,
    private_key: rsa.RSAPrivateKey,
    overrides: FakeSupabase,
):
    response = await client.get(
        "/api/v1/media/search?tag=Family",
        headers={"Authorization": f"Bearer {make_token(private_key)}"},
    )
    assert response.status_code == 200
    assert ("user_id", "user-123") in overrides.query.filters
    assert ("tags", ["Family"]) in overrides.query.filters


@pytest.mark.anyio
async def test_gallery_and_details_isolate_two_users(
    client: AsyncClient, private_key: rsa.RSAPrivateKey
):
    records = [
        {
            "id": str(uuid4()), "user_id": owner, "device_id": "nas",
            "local_file_id": owner + ".jpg", "file_type": "image", "tags": ["Family"],
            "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z",
        }
        for owner in ("alice", "bob")
    ]

    class ScopedQuery(FakeQuery):
        def execute(self) -> SimpleNamespace:
            rows = self.rows
            for key, value in self.filters:
                rows = [row for row in rows if row[key] == value]
            return SimpleNamespace(data=rows)

    class ScopedClient:
        def table(self, _: str) -> ScopedQuery:
            return ScopedQuery(records)

    app.dependency_overrides[get_supabase_client] = lambda: ScopedClient()
    for owner in ("alice", "bob"):
        headers = {"Authorization": f"Bearer {make_token(private_key, subject=owner)}"}
        response = await client.get("/api/v1/media", headers=headers)
        assert response.status_code == 200
        assert [row["user_id"] for row in response.json()["results"]] == [owner]
        own = next(row for row in records if row["user_id"] == owner)
        other = next(row for row in records if row["user_id"] != owner)
        assert (await client.get(f"/api/v1/media/{own['id']}", headers=headers)).status_code == 200
        assert (await client.get(f"/api/v1/media/{other['id']}", headers=headers)).status_code == 404


@pytest.mark.anyio
async def test_gallery_pagination_filters_and_validation(
    client: AsyncClient, private_key: rsa.RSAPrivateKey, overrides: FakeSupabase
):
    overrides.query.rows = [
        {
            "id": str(uuid4()), "user_id": "user-123", "device_id": "nas",
            "local_file_id": str(i), "file_type": "image",
            "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z",
        } for i in range(3)
    ]
    headers = {"Authorization": f"Bearer {make_token(private_key)}"}
    result = await client.get("/api/v1/media?limit=2&file_type=image&tag=Family", headers=headers)
    assert result.status_code == 200
    assert len(result.json()["results"]) == 2
    assert result.json()["has_more"] is True
    assert ("file_type", "image") in overrides.query.filters
    assert ("tags", ["Family"]) in overrides.query.filters
    for query in ("limit=0", "offset=-1", "file_type=invalid", "tag=%20", "sort=invalid"):
        assert (await client.get("/api/v1/media?" + query, headers=headers)).status_code == 422
    assert (await client.get("/api/v1/media")).status_code == 401


@pytest.mark.anyio
async def test_cors_allows_local_frontend_but_not_untrusted_origins(client: AsyncClient):
    for origin, expected in (("http://127.0.0.1:5173", 200), ("https://untrusted.test", 400)):
        response = await client.options("/api/v1/media", headers={
            "Origin": origin, "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        })
        assert response.status_code == expected
        if expected == 200:
            assert response.headers["access-control-allow-origin"] == origin
        else:
            assert "access-control-allow-origin" not in response.headers
