"""ASGI application entry point."""

from fastapi import FastAPI

from .config import get_settings
from .routes import router

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Secure media metadata synchronization and similarity search API.",
    debug=settings.debug,
    docs_url="/docs" if settings.app_environment != "production" else None,
    redoc_url="/redoc" if settings.app_environment != "production" else None,
)
app.include_router(router)
