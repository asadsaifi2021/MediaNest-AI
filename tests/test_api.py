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


def make_token(private_key: rsa.RSAPrivateKey, *, expired: bool = False) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "user-123",
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
        "service": "Media Archive Cloud API",
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
    assert rpc_name == "match_faces"
    assert params["p_user_id"] == "user-123"
    assert params["match_count"] == 5


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
