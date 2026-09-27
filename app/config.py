"""Typed application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, loaded from the environment or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_name: str = "Media Archive Cloud API"
    app_environment: str = "development"
    debug: bool = False
    supabase_url: AnyHttpUrl | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_jwt_audience: str = "authenticated"
    supabase_jwt_issuer: str | None = None
    jwks_cache_lifespan_seconds: int = Field(default=300, gt=0)
    jwks_request_timeout_seconds: float = Field(default=5.0, gt=0)
    edge_hmac_secret: SecretStr | None = None
    edge_signature_max_age_seconds: int = Field(default=300, gt=0)
    face_match_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

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
