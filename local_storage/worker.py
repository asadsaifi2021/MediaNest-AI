"""Run with python -m local_storage.worker. One process; Ctrl+C stops safely."""
import argparse
import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path

import jwt
from fastapi import HTTPException

from app.transfers import ISSUER

from .ai import AISettings, index
from .main import ROOT, get_local_settings, media_directory, metadata_call
from .queue import Queue

log = logging.getLogger("medianest.worker")


@contextmanager
def process_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def call(settings, path, payload):
    now = int(time.time())
    node = str(settings.local_node_id)
    token = jwt.encode({"sub": node, "media_id": node, "purpose": "worker",
        "iat": now, "exp": now + 60, "iss": ISSUER, "aud": node},
        settings.local_node_secret.get_secret_value(), algorithm="HS256")
    return metadata_call(settings, token, path, payload)


def recover(settings, owner: str):
    # Only this registered node's owner; never import other filesystem users.
    base = settings.media_root / owner
    if not base.exists():
        return
    for manifest_path in base.glob("*/manifest.json"):
        if manifest_path.is_symlink() or (manifest_path.parent / ".synced").exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
            upload = manifest["upload"]
            if upload["sub"] != owner:
                continue
            directory = media_directory(settings, upload)
            if directory.resolve() != manifest_path.parent.resolve():
                continue
            call(settings, "/api/v1/local/recover",
                 {"upload": {k: v for k, v in upload.items() if k != "sub"},
                  "receipt": manifest["receipt"]})
            (directory / ".synced").touch()
        except (HTTPException, ValueError, OSError, KeyError):
            log.warning("An unsynchronized local file will be retried.")


def tick(settings, ai_settings, queue):
    response = call(settings, "/api/v1/local/tasks", {})
    recover(settings, response["owner"])
    for task in response["tasks"]:
        queue.add(task)
    job = queue.take()
    if not job:
        return
    task = json.loads(job["payload"])
    result_ready = bool(job["result"])
    try:
        # Never run canceled/superseded tasks or tasks for a previous node owner.
        current = {t["ai_request_id"] for t in response["tasks"]}
        if task["user_id"] != response["owner"] or job["id"] not in current:
            current = call(settings, "/api/v1/local/task-current",
                           {"media_id": task["id"], "request_id": job["id"]})
            if task["user_id"] != response["owner"] or not current["current"]:
                queue.finish(job["id"])
            else:
                queue.retry(job["id"], job["attempts"])
            return
        if job["result"]:
            result = json.loads(job["result"])
        else:
            directory = media_directory(settings, {"sub": task["user_id"], "media_id": task["id"]})
            if not (directory / "original").is_file():
                raise RuntimeError("Original is unavailable on this PC.")
            result = index(directory, task, ai_settings)
            queue.result(job["id"], result)
            result_ready = True
        call(settings, "/api/v1/local/index-result", result)
        queue.finish(job["id"])
    except Exception as exc:
        # No paths, credentials, transcripts or biometric vectors in logs.
        log.warning("Indexing or synchronization failed (%s); retry scheduled.", type(exc).__name__)
        if job["attempts"] >= 2 and not result_ready:
            message = "Local processing failed. Check models, license opt-in, dependencies and original file."
            failure = {"media_id": task["id"], "request_id": job["id"], "error": message[:200]}
            try:
                call(settings, "/api/v1/local/index-result", failure)
                queue.finish(job["id"])
                return
            except Exception:
                pass
        queue.retry(job["id"], job["attempts"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--state-dir", type=Path, default=ROOT / "local-state")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    with process_lock(args.state_dir / "worker.lock"):
        queue = Queue(args.state_dir / "jobs.sqlite3")
        try:
            while True:
                try:
                    tick(get_local_settings(), AISettings(), queue)
                except Exception as exc:
                    log.warning("Metadata service unavailable (%s).", type(exc).__name__)
                if args.once:
                    break
                time.sleep(10)
        except KeyboardInterrupt:
            log.info("Worker stopped; unfinished jobs will resume next time.")
        finally:
            queue.db.close()


if __name__ == "__main__":
    main()
