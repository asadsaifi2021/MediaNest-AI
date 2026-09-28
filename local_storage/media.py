"""Bounded, local-only FFmpeg conversion. Never pass user-supplied URLs to FFmpeg."""
import hashlib
import json
import subprocess
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageDraw


def run(args: list[str], timeout: int = 600) -> bytes:
    try:
        return subprocess.run(args, check=True, capture_output=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except FileNotFoundError as exc:
        raise HTTPException(503, "Install FFmpeg and ffprobe on the storage PC first.") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(415, "Media could not be decoded within the processing limits.") from exc


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def process_av(stage: Path, claims: dict, digest: str) -> dict:
    original = str(stage / "original")
    safe_input = ["-protocol_whitelist", "file,pipe", "-format_whitelist",
                  "mov,matroska,webm,mp3,wav,flac,ogg", "-i", original]
    probe = json.loads(run(["ffprobe", "-v", "error", *safe_input,
                           "-show_streams", "-show_format", "-of", "json"], 30))
    streams = probe.get("streams", [])
    video = next((s for s in streams if s["codec_type"] == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s["codec_type"] == "audio"), None)
    is_video = claims["content_type"].startswith("video/")
    if (is_video and not video) or (not is_video and (not audio or video)):
        raise HTTPException(415, "File contents do not match the selected media type.")
    duration = float(probe.get("format", {}).get("duration", 0))
    if not 0 < duration <= 14400:
        raise HTTPException(415, "Media must have a known duration of at most four hours.")
    if video and (video.get("width", 0) * video.get("height", 0) > 34_000_000):
        raise HTTPException(415, "Video frame size exceeds the processing limit.")
    common = ["ffmpeg", "-nostdin", "-v", "error", "-y", *safe_input, "-map_metadata", "-1",
              "-threads", "2"]
    playback = stage / "playback"
    if is_video:
        run([*common, "-map", "0:v:0", "-map", "0:a:0?", "-vf",
             "scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
             "-c:v", "libx264", "-preset", "fast", "-crf", "25", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-f", "mp4", str(playback)])
        run([*common, "-map", "0:v:0", "-frames:v", "1",
             "-vf", "scale=640:640:force_original_aspect_ratio=decrease", str(stage / "thumbnail.jpg")])
    else:
        run([*common, "-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", "160k",
             "-movflags", "+faststart", "-f", "mp4", str(playback)])
        # A local neutral cover, not a fabricated image or cloud artwork.
        cover = Image.new("RGB", (640, 360), "#172e29")
        ImageDraw.Draw(cover).text((280, 165), "AUDIO", fill="#d0deab")
        cover.save(stage / "thumbnail.jpg", "JPEG")
    if playback.stat().st_size > 1024**3:
        raise HTTPException(413, "Converted playback file exceeds 1 GiB.")
    thumbnail = stage / "thumbnail.jpg"
    return {"original_sha256": digest, "thumbnail_sha256": checksum(thumbnail),
            "thumbnail_size": thumbnail.stat().st_size, "playback_sha256": checksum(playback),
            "playback_size": playback.stat().st_size,
            "playback_type": "video/mp4" if is_video else "audio/mp4",
            "media_info": {"duration": duration, "width": video.get("width") if video else None,
                           "height": video.get("height") if video else None,
                           "video_codec": video.get("codec_name") if video else None,
                           "audio_codec": audio.get("codec_name") if audio else None}}
