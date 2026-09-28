"""Typed application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, AnyHttpUrl, Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Runtime settings, loaded from the environment or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    app_name: str = "MediaNest AI"
    app_environment: str = "development"
    debug: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:5173", "http://127.0.0.1:5173",
    ])
    supabase_url: AnyHttpUrl | None = None
    supabase_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )
    supabase_jwt_audience: str = "authenticated"
    supabase_jwt_issuer: str | None = None
    jwks_cache_lifespan_seconds: int = Field(default=300, gt=0)
    jwks_request_timeout_seconds: float = Field(default=5.0, gt=0)
    edge_hmac_secret: SecretStr | None = None
    edge_signature_max_age_seconds: int = Field(default=300, gt=0)
    face_match_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    local_node_id: str | None = None
    local_node_secret: SecretStr | None = None

    @computed_field
    @property
    def jwks_url(self) -> str | None:
        if self.supabase_url is None:
            return None
        return f"{str(self.supabase_url).rstrip('/')}/auth/v1/.well-known/jwks.json"

    @computed_field
    @property
    def jwt_issuer(self) -> str | None:
        if self.supabase_jwt_issuer:
            return self.supabase_jwt_issuer.rstrip("/")
        if self.supabase_url is None:
            return None
        return f"{str(self.supabase_url).rstrip('/')}/auth/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
