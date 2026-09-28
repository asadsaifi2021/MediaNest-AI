import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import verify_supabase_jwt
from app.main import app
from app.routes import get_supabase_client
from local_storage.ai import AISettings, index
from local_storage.queue import Queue
from local_storage.worker import call, tick
from tests.test_photo_flow import NODE, OTHER, OWNER, flow, grant, photo, upload  # noqa: F401


def test_av_upload_playback_cookie_and_range(flow, monkeypatch):  # noqa: F811
    cloud, storage, db, local = flow
    raw = b"test-video-bytes"
    def process(stage, claims, digest):
        (stage / "thumbnail.jpg").write_bytes(b"thumbnail")
        (stage / "playback").write_bytes(b"0123456789")
        return {"original_sha256": digest, "thumbnail_sha256": "b" * 64,
                "thumbnail_size": 9, "playback_sha256": "c" * 64,
                "playback_size": 10, "playback_type": "video/mp4",
                "media_info": {"duration": 2.0, "width": 320, "height": 240}}
    monkeypatch.setattr("local_storage.main.process_av", process)
    media_id = str(uuid4())
    grant = cloud.post(f"/api/v1/storage-nodes/{NODE}/upload-grant", json={
        "media_id": media_id, "filename": "movie.mp4", "content_type": "video/mp4",
        "byte_size": len(raw)}).json()
    result = storage.post("/upload", content=raw, headers={"Authorization": "Bearer " + grant["token"]})
    assert result.status_code == 200, result.text
    access = cloud.post(f"/api/v1/media/{media_id}/access-grant?kind=playback").json()
    assert storage.post("/playback-session").status_code == 401
    ready = storage.post("/playback-session", headers={"Authorization": "Bearer " + access["token"]})
    assert ready.status_code == 200
    assert "HttpOnly" in ready.headers["set-cookie"]
    assert "SameSite=strict" in ready.headers["set-cookie"]
    response = storage.get(f"/objects/{media_id}/playback", headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    db.nodes[0]["disabled_at"] = "disabled"
    assert storage.get(f"/objects/{media_id}/playback").status_code == 404


def test_node_recovery_uses_registered_owner_not_browser_session(flow):  # noqa: F811
    _, _, db, local = flow
    result = call(local, "/api/v1/local/recover", {
        "upload": {"media_id": str(uuid4()), "filename": "photo.jpg",
                   "byte_size": 10, "content_type": "image/jpeg"},
        "receipt": {"original_sha256": "a"*64, "thumbnail_sha256": "b"*64, "thumbnail_size": 10}})
    assert result["status"] == "complete"
    assert db.receipts[0]["p_user_id"] == OWNER
    db.nodes[0]["disabled_at"] = "disabled"
    with pytest.raises(Exception):
        call(local, "/api/v1/local/recover", {})


def test_face_crops_require_owned_live_embeddings_and_exact_scope(flow):  # noqa: F811
    cloud, storage, db, local = flow
    raw = photo()
    media_id = upload(storage, grant(cloud, raw).json()["token"], raw).json()["media_id"]
    face_id = str(uuid4())
    db.faces.append({"id": face_id, "user_id": OWNER, "media_id": media_id})
    directory = local.media_root / OWNER / media_id / "faces"
    directory.mkdir()
    (directory / (face_id + ".jpg")).write_bytes(raw)
    access = cloud.post(f"/api/v1/faces/{face_id}/preview-grant")
    assert access.status_code == 200, access.text
    headers = {"Authorization": "Bearer " + access.json()["token"]}
    assert storage.get(f"/faces/{media_id}/{face_id}", headers=headers).status_code == 200
    assert storage.get(f"/faces/{media_id}/{uuid4()}", headers=headers).status_code == 403
    app.dependency_overrides[verify_supabase_jwt] = lambda: {"sub": OTHER}
    assert cloud.post(f"/api/v1/faces/{face_id}/preview-grant").status_code == 404
    db.faces.clear()
    assert storage.get(f"/faces/{media_id}/{face_id}", headers=headers).status_code == 404


def test_queue_restart_resumes_job_and_retains_result(tmp_path):
    path = tmp_path / "state.sqlite3"
    task = {"ai_request_id": str(uuid4()), "id": str(uuid4())}
    queue = Queue(path)
    queue.add(task)
    queue.add(task)
    assert queue.db.execute("select count(*) from jobs").fetchone()[0] == 1
    job = queue.take()
    queue.result(job["id"], {"tags": ["car"]})
    queue.db.close()
    queue = Queue(path)
    resumed = queue.take()
    assert resumed["id"] == job["id"]
    assert json.loads(resumed["result"]) == {"tags": ["car"]}
    queue.finish(job["id"])
    assert queue.take() is None
    assert queue.db.execute("select result from jobs").fetchone()[0] is None
    queue.db.close()


def test_ai_does_not_download_models_or_run_faces_without_opt_in(tmp_path):
    task = {"id": str(uuid4()), "ai_request_id": str(uuid4()), "file_type": "image",
            "ai_options": {"objects": True, "faces": False}}
    with pytest.raises(RuntimeError, match="license"):
        index(tmp_path, task, AISettings(_env_file=None))
    task["ai_options"] = {"faces": True}
    with pytest.raises(RuntimeError, match="ENABLE_FACE"):
        index(tmp_path, task, AISettings(_env_file=None))


def test_worker_reuses_saved_inference_result_after_network_failure(tmp_path, monkeypatch):
    from local_storage.main import LocalSettings
    task = {"id": str(uuid4()), "user_id": OWNER, "ai_request_id": str(uuid4()),
            "file_type": "image", "ai_options": {"objects": True}}
    local = LocalSettings(_env_file=None, local_node_id=NODE, local_node_secret="x"*40,
                          media_root=tmp_path / "media")
    target = local.media_root / OWNER / task["id"]
    target.mkdir(parents=True)
    (target / "original").write_bytes(b"photo")
    queue = Queue(tmp_path / "queue.sqlite3")
    computations = []
    calls = []
    def infer(*_):
        computations.append(True)
        return {"media_id": task["id"], "request_id": task["ai_request_id"], "tags": ["car"]}
    def api(_, path, payload):
        if path.endswith("/tasks"):
            return {"owner": OWNER, "tasks": [task]}
        calls.append(payload)
        if len(calls) == 1:
            raise OSError("offline")
        return {"status": "applied"}
    monkeypatch.setattr("local_storage.worker.call", api)
    monkeypatch.setattr("local_storage.worker.index", infer)
    tick(local, AISettings(_env_file=None), queue)
    queue.db.execute("update jobs set next_at=0")
    queue.db.commit()
    tick(local, AISettings(_env_file=None), queue)
    assert len(computations) == 1
    assert len(calls) == 2 and "error" not in calls[1]
    assert queue.take() is None
    queue.db.close()


def test_tag_edit_ownership_and_search_rpc_parameters():
    media_id = str(uuid4())
    row = {"id": media_id, "user_id": OWNER, "device_id": "pc", "local_file_id": "id",
           "file_type": "image", "tags": [], "created_at": "2026-01-01T00:00:00Z",
           "updated_at": "2026-01-01T00:00:00Z"}
    class Query:
        def __init__(self):
            self.filters = {}
        def update(self, values):
            self.values = values
            return self
        def eq(self, key, value):
            self.filters[key] = value
            return self
        def execute(self):
            if all(row[k] == v for k, v in self.filters.items()):
                row.update(self.values)
                return SimpleNamespace(data=[row])
            return SimpleNamespace(data=[])
    class DB:
        def table(self, name):
            assert name == "media_metadata"
            return Query()
        def rpc(self, name, params):
            assert name == "search_archive"
            assert params["p_owner"] == OWNER
            assert params["p_query"] == 'holiday ),user_id.eq.other'
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=[row]))
    app.dependency_overrides[verify_supabase_jwt] = lambda: {"sub": OWNER}
    app.dependency_overrides[get_supabase_client] = lambda: DB()
    try:
        with TestClient(app) as client:
            response = client.post(f"/api/v1/media/{media_id}/tags", json={"tags": [" Trip ", "trip"]})
            assert response.status_code == 200
            assert response.json()["tags"] == ["Trip"]
            assert client.post(f"/api/v1/media/{media_id}/tags", json={"tags": [" "]}).status_code == 422
            assert client.get("/api/v1/media", params={"q": 'holiday ),user_id.eq.other'}).status_code == 200
            app.dependency_overrides[verify_supabase_jwt] = lambda: {"sub": OTHER}
            assert client.post(f"/api/v1/media/{media_id}/tags", json={"tags": ["stolen"]}).status_code == 404
            assert row["tags"] == ["Trip"]
    finally:
        app.dependency_overrides.clear()
