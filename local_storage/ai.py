"""Offline model adapters. No implicit weight downloads; no remote inference."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid5

from pydantic_settings import BaseSettings, SettingsConfigDict

from .media import checksum


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent / ".env", extra="ignore")
    yolo_model_path: Path | None = None
    whisper_model_path: Path | None = None
    yunet_model_path: Path | None = None
    sface_model_path: Path | None = None
    enable_face_recognition: bool = False
    yolo_license_accepted: bool = False


def model_file(path: Path | None, label: str) -> Path:
    if path is None or not path.is_file():
        raise RuntimeError(f"Configure an existing local {label} model file.")
    return path


@lru_cache(maxsize=2)
def yolo(path: str, version: str):
    from ultralytics import YOLO, settings
    settings.update({"sync": False})
    return YOLO(path, task="detect")


@lru_cache(maxsize=1)
def whisper(path: str, version: str):
    from faster_whisper import WhisperModel
    return WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=2,
                        local_files_only=True)


def frames(directory: Path, media_type: str):
    import cv2
    import numpy as np
    from PIL import Image, ImageOps
    if media_type == "image":
        with Image.open(directory / "original") as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1920, 1920))
            yield 0, cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    elif media_type == "video":
        capture = cv2.VideoCapture(str(directory / "playback"))
        try:
            count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            for index in range(0, max(1, count), max(1, count // 30)):
                capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = capture.read()
                if ok:
                    yield index, frame
                if index // max(1, count // 30) >= 29:
                    break
        finally:
            capture.release()


def index(directory: Path, task: dict, settings: AISettings) -> dict:
    options = task["ai_options"]
    media_type = task["file_type"]
    result = {"media_id": task["id"], "request_id": task["ai_request_id"], "models": {}}
    detect = options.get("objects") and media_type != "audio"
    face = options.get("faces") and media_type != "audio"
    if detect:
        if not settings.yolo_license_accepted:
            raise RuntimeError("Review the YOLOv8 license and set YOLO_LICENSE_ACCEPTED=true.")
        model = model_file(settings.yolo_model_path, "YOLOv8")
        version = checksum(model)
        detector = yolo(str(model), version)
        result["models"]["objects"] = "yolov8:" + version
        result["tags"] = []
    if face:
        if not settings.enable_face_recognition:
            raise RuntimeError("Face processing requires ENABLE_FACE_RECOGNITION=true on this PC.")
        import cv2
        detector_path = model_file(settings.yunet_model_path, "YuNet")
        recognizer_path = model_file(settings.sface_model_path, "SFace")
        face_detector = cv2.FaceDetectorYN.create(str(detector_path), "", (320, 320),
                                                  score_threshold=0.9, top_k=100)
        recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")
        model_id = "sface128-pad512:" + hashlib.sha256(
            (checksum(detector_path) + checksum(recognizer_path)).encode()).hexdigest()
        result["models"]["faces"] = model_id
        result["faces"] = []
    if detect or face:
        for frame_id, frame in frames(directory, media_type):
            if detect:
                predictions = detector.predict(frame, conf=0.4, device="cpu", verbose=False)
                tags = {predictions[0].names[int(c)] for c in predictions[0].boxes.cls.tolist()}
                result["tags"] = sorted(set(result["tags"]) | tags)[:50]
            if face and len(result["faces"]) < 100:
                face_detector.setInputSize((frame.shape[1], frame.shape[0]))
                _, detected = face_detector.detect(frame)
                for row in ([] if detected is None else detected):
                    if len(result["faces"]) == 100:
                        break
                    vector = recognizer.feature(recognizer.alignCrop(frame, row)).flatten()
                    if len(vector) != 128:
                        raise RuntimeError("Unexpected face vector dimension")
                    # Zero-padding preserves cosine distances; never mix with other 512-D models.
                    embedding = vector.astype(float).tolist() + [0.0] * 384
                    identity = f"{model_id}:{frame_id}:" + ",".join(str(round(float(x))) for x in row[:4])
                    face_id = str(uuid5(UUID(task["id"]), identity))
                    from PIL import Image
                    face_dir = directory / "faces"
                    if face_dir.is_symlink():
                        raise RuntimeError("Linked face directories are not allowed")
                    face_dir.mkdir(exist_ok=True)
                    x, y, w, h = [int(float(v)) for v in row[:4]]
                    crop = frame[max(0, y):min(frame.shape[0], y+h),
                                 max(0, x):min(frame.shape[1], x+w)]
                    if crop.size:
                        destination = face_dir / (face_id + ".jpg")
                        if destination.is_symlink():
                            raise RuntimeError("Linked face files are not allowed")
                        image = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                        image.thumbnail((256, 256))
                        image.save(destination, "JPEG", quality=85)
                    result["faces"].append({"id": face_id,
                        "embedding": embedding, "model_id": model_id, "vector_version": 1})
    if options.get("transcription") and media_type in ("video", "audio"):
        manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
        if media_type == "audio" or manifest["receipt"].get("media_info", {}).get("audio_codec"):
            path = settings.whisper_model_path
            if path is None or not (path / "model.bin").is_file():
                raise RuntimeError("Configure WHISPER_MODEL_PATH to a downloaded faster-whisper model.")
            version = checksum(path / "model.bin")
            result["models"]["transcription"] = "faster-whisper:" + version
            segments, _ = whisper(str(path), version).transcribe(str(directory / "playback"),
                beam_size=3, vad_filter=True, condition_on_previous_text=False)
            lines = []
            length = 0
            for segment in segments:
                line = f"[{segment.start:.1f}–{segment.end:.1f}s] {segment.text.strip()}"
                length += len(line) + 1
                if length > 200000:
                    raise RuntimeError("Transcript exceeds the metadata size limit.")
                lines.append(line)
            result["transcription"] = "\n".join(lines)
    return result
