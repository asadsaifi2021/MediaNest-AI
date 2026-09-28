from types import SimpleNamespace
from uuid import uuid4

from local_storage.ai import AISettings, index


def task(kind, options):
    return {"id": str(uuid4()), "ai_request_id": str(uuid4()),
            "file_type": kind, "ai_options": options}


def test_yolo_collects_unique_suggestions_with_model_fingerprint(tmp_path, monkeypatch):
    model = tmp_path / "yolov8n.pt"
    model.write_bytes(b"test-only model stand-in")
    predictions = [SimpleNamespace(names={0: "car", 1: "dog"},
                   boxes=SimpleNamespace(cls=SimpleNamespace(tolist=lambda: [0, 1, 0])))]
    model_stub = SimpleNamespace(predict=lambda *a, **kw: predictions)
    monkeypatch.setattr("local_storage.ai.yolo", lambda *_: model_stub)
    monkeypatch.setattr("local_storage.ai.frames", lambda *_: [(0, object()), (1, object())])
    result = index(tmp_path, task("image", {"objects": True}), AISettings(
        _env_file=None, yolo_model_path=model, yolo_license_accepted=True))
    assert result["tags"] == ["car", "dog"]
    assert result["models"]["objects"].startswith("yolov8:")
    assert len(result["models"]["objects"].split(":")[1]) == 64
    assert "faces" not in result


def test_transcription_is_timestamped_and_uses_only_local_playback(tmp_path, monkeypatch):
    model = tmp_path / "whisper"
    model.mkdir()
    (model / "model.bin").write_bytes(b"test-only model stand-in")
    (tmp_path / "manifest.json").write_text('{"receipt":{"media_info":{"audio_codec":"aac"}}}')
    calls = []
    def transcribe(path, **kwargs):
        calls.append((path, kwargs))
        return iter([SimpleNamespace(start=0.0, end=1.5, text=" Hello world ")]), None
    monkeypatch.setattr("local_storage.ai.whisper",
                        lambda *_: SimpleNamespace(transcribe=transcribe))
    result = index(tmp_path, task("audio", {"transcription": True}),
                   AISettings(_env_file=None, whisper_model_path=model))
    assert result["transcription"] == "[0.0–1.5s] Hello world"
    assert calls[0][0] == str(tmp_path / "playback")
    assert calls[0][1]["vad_filter"] is True
