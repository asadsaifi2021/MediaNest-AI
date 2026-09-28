"""Optional built frontend hosting for a single private Tailscale HTTPS origin."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def mount_web(app: FastAPI):
    if not (DIST / "index.html").is_file():
        return
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")
    app.mount("/samples", StaticFiles(directory=DIST / "samples"), name="samples")

    @app.get("/{path:path}", include_in_schema=False)
    async def web(path: str):
        if path.startswith(("api/", "objects/")):
            raise HTTPException(404, "Not found")
        public = {"sw.js", "offline.html", "manifest.webmanifest", "icon.svg"}
        target = DIST / (path if path in public else "index.html")
        media = "application/manifest+json" if path == "manifest.webmanifest" else None
        return FileResponse(target, media_type=media, headers={
            "Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"})
