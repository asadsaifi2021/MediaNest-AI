"""ASGI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError

from .config import get_settings
from .database import database_error_detail
from .indexing import router as indexing_router
from .routes import router
from .storage import router as storage_router
from .transfers import router as transfer_router

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.3.0",
    description="MediaNest AI metadata API for a private, locally stored media archive.",
    debug=settings.debug,
    docs_url="/docs" if settings.app_environment != "production" else None,
    redoc_url="/redoc" if settings.app_environment != "production" else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(router)
app.include_router(storage_router)
app.include_router(transfer_router)
app.include_router(indexing_router)


@app.exception_handler(APIError)
async def database_failure(request, exc):
    return JSONResponse(status_code=503, content={"detail": database_error_detail(exc)})

from .web import mount_web  # noqa: E402

mount_web(app)
