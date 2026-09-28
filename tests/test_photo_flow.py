import hashlib
import io
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.auth import verify_supabase_jwt
from app.config import Settings, get_settings
from app.main import app
from app.routes import get_supabase_client
from app.transfers import ISSUER
from local_storage.main import LocalSettings, get_local_settings
from local_storage.main import app as local_app

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
NODE = "33333333-3333-4333-8333-333333333333"
KEY = "test-node-secret-never-used-in-production-1234"


class DB:
    def __init__(self):
        self.nodes = [{"id": NODE, "user_id": OWNER, "disabled_at": None,
                       "base_url": "http://127.0.0.1:8100", "device_id": "pc"}]
        self.objects = []
        self.receipts = []
        self.fail_completion = False

    def table(self, table):
        rows = self.nodes if table == "storage_nodes" else self.objects

        class Query:
            def __init__(self):
                self.filters = []

            def select(self, *_):
                return self

            def eq(self, key, value):
                self.filters.append((key, value))
                return self

            def limit(self, *_):
                return self

            def execute(self):
                return SimpleNamespace(data=[
                    r for r in rows if all(r[k] == v for k, v in self.filters)
                ])
        return Query()

    def rpc(self, name, params):
        assert name == "complete_photo_upload"
        if self.fail_completion:
            raise RuntimeError("offline")
        self.receipts.append(params)
        for kind in ("original", "thumbnail"):
            self.objects.append({
                "id": str(uuid4()), "user_id": params["p_user_id"],
                "storage_node_id": params["p_node_id"], "media_id": params["p_media_id"],
                "kind": kind, "object_key": str(uuid4()),
            })
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=params["p_media_id"]))


@pytest.fixture
def flow(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, local_node_id=NODE, local_node_secret=KEY)
    local = LocalSettings(_env_file=None, local_node_id=NODE, local_node_secret=KEY,
                          media_root=tmp_path / "photos")
    db = DB()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_supabase_client] = lambda: db
    app.dependency_overrides[verify_supabase_jwt] = lambda: {"sub": OWNER}
    local_app.dependency_overrides[get_local_settings] = lambda: local
    with TestClient(app) as cloud, TestClient(local_app) as storage:
        def post(url, *, content, headers, **kwargs):
            assert url.startswith("http://127.0.0.1:8000")
            return cloud.post(url.removeprefix("http://127.0.0.1:8000"),
                              content=content, headers=headers)
        monkeypatch.setattr("local_storage.main.httpx.post", post)
        yield cloud, storage, db, local
    app.dependency_overrides.clear()
    local_app.dependency_overrides.clear()


def photo():
    output = io.BytesIO()
    image = Image.new("RGB", (800, 600), "green")
    image.save(output, "JPEG", exif=Image.Exif())
    return output.getvalue()


def grant(cloud, raw, media_id=None):
    return cloud.post(f"/api/v1/storage-nodes/{NODE}/upload-grant", json={
        "media_id": media_id or str(uuid4()), "filename": "holiday.jpg",
        "content_type": "image/jpeg", "byte_size": len(raw),
    })


def upload(storage, token, raw):
    return storage.post("/upload", content=raw,
                        headers={"Authorization": "Bearer " + token})


def test_photo_upload_thumbnail_and_authorized_original(flow):
    cloud, storage, db, local = flow
    raw = photo()
    ticket = grant(cloud, raw).json()["token"]
    response = upload(storage, ticket, raw)
    assert response.status_code == 200, response.text
    media_id = response.json()["media_id"]
    directory = local.media_root / OWNER / media_id
    assert (directory / "original").read_bytes() == raw
    with Image.open(directory / "thumbnail.jpg") as thumb:
        assert max(thumb.size) <= 640
        assert not thumb.getexif()
    assert db.receipts[0]["p_original_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "image" not in db.receipts[0]  # metadata callback contains no media bytes
    for kind in ("thumbnail", "original"):
        access = cloud.post(f"/api/v1/media/{media_id}/access-grant?kind={kind}").json()
        result = storage.get(f"/objects/{media_id}/{kind}",
                             headers={"Authorization": "Bearer " + access["token"]})
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        if kind == "original":
            assert result.content == raw
    assert storage.get(f"/objects/{media_id}/original").status_code == 401


def test_upload_retries_preserve_local_files_and_refuse_different_bytes(flow):
    cloud, storage, db, local = flow
    raw = photo()
    ticket = grant(cloud, raw).json()["token"]
    db.fail_completion = True
    assert upload(storage, ticket, raw).status_code == 502
    saved = list(local.media_root.glob("*/*/original"))
    assert len(saved) == 1 and saved[0].read_bytes() == raw
    db.fail_completion = False
    assert upload(storage, ticket, raw).status_code == 200
    assert len(list(local.media_root.glob("*/*/original"))) == 1
    changed = b"x" + raw[1:]
    assert upload(storage, ticket, changed).status_code == 409
    assert saved[0].read_bytes() == raw


def test_disabled_nodes_expired_permissions_wrong_owner_and_scope(flow):
    cloud, storage, db, local = flow
    raw = photo()
    ticket = grant(cloud, raw).json()["token"]
    claims = jwt.decode(ticket, KEY, algorithms=["HS256"], audience=NODE, issuer=ISSUER)
    expired = jwt.encode({**claims, "iat": 1, "exp": 2}, KEY, algorithm="HS256")
    assert upload(storage, expired, raw).status_code == 401
    wrong_node = jwt.encode({**claims, "aud": str(uuid4())}, KEY, algorithm="HS256")
    assert upload(storage, wrong_node, raw).status_code == 401
    read = jwt.encode({**claims, "purpose": "read"}, KEY, algorithm="HS256")
    assert upload(storage, read, raw).status_code == 403
    # Browser ticket alone cannot claim that the node completed an upload.
    assert cloud.post("/api/v1/local/validate", json={},
                      headers={"Authorization": "Bearer " + ticket}).status_code == 401
    app.dependency_overrides[verify_supabase_jwt] = lambda: {"sub": OTHER}
    assert grant(cloud, raw).status_code == 404
    app.dependency_overrides[verify_supabase_jwt] = lambda: {"sub": OWNER}
    db.nodes[0]["disabled_at"] = "2026-09-27"
    assert grant(cloud, raw).status_code == 404
    assert upload(storage, ticket, raw).status_code == 404
    assert not local.media_root.exists()


def test_invalid_images_and_size_do_not_leave_files(flow):
    cloud, storage, _, local = flow
    raw = b"not an image"
    ticket = grant(cloud, raw).json()["token"]
    assert upload(storage, ticket, raw).status_code == 415
    assert upload(storage, ticket, raw + b"too long").status_code == 413
    assert upload(storage, ticket, raw[:-1]).status_code == 400
    assert not list(local.media_root.glob("*/*/original"))
    assert not list(local.media_root.glob("*/.incoming-*"))


def test_read_checks_revocation_and_exact_resource(flow):
    cloud, storage, db, _ = flow
    raw = photo()
    media_id = upload(storage, grant(cloud, raw).json()["token"], raw).json()["media_id"]
    access = cloud.post(f"/api/v1/media/{media_id}/access-grant").json()["token"]
    headers = {"Authorization": "Bearer " + access}
    assert storage.get(f"/objects/{media_id}/original", headers=headers).status_code == 403
    assert storage.get(f"/objects/{uuid4()}/thumbnail", headers=headers).status_code == 403
    app.dependency_overrides[verify_supabase_jwt] = lambda: {"sub": OTHER}
    assert cloud.post(f"/api/v1/media/{media_id}/access-grant").status_code == 404
    db.nodes[0]["disabled_at"] = "disabled"
    assert storage.get(f"/objects/{media_id}/thumbnail", headers=headers).status_code == 404


def test_upload_filename_is_not_a_path(flow):
    cloud, _, _, _ = flow
    response = cloud.post(f"/api/v1/storage-nodes/{NODE}/upload-grant", json={
        "media_id": str(uuid4()), "filename": "../escape.jpg",
        "content_type": "image/jpeg", "byte_size": 10,
    })
    assert response.status_code == 422
