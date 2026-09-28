"""Supabase Data API client construction and error classification."""

from functools import lru_cache
from typing import Any, Protocol

import httpx
import jwt
from postgrest import SyncPostgrestClient


class SupabaseQueryClient(Protocol):
    """The subset of PostgREST used by the API and its test doubles."""

    def table(self, table: str) -> Any: ...

    def rpc(self, function_name: str, params: dict[str, Any]) -> Any: ...


class InvalidSupabaseKey(ValueError):
    """Raised when a public/anonymous key is configured for the trusted backend."""


def _data_api_headers(key: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "apikey": key,
    }
    if key.startswith("sb_secret_"):
        # New Supabase secret keys are opaque API keys, not JWTs. Sending one in
        # Authorization makes the gateway reject it as an invalid JWT.
        return headers
    if key.startswith("sb_publishable_"):
        raise InvalidSupabaseKey("A publishable key cannot be used by the trusted backend")

    # Legacy service_role keys are JWTs and must be supplied as both the API key
    # and bearer credential so PostgREST assumes the service_role database role.
    try:
        claims = jwt.decode(key, options={"verify_signature": False})
    except jwt.InvalidTokenError as exc:
        raise InvalidSupabaseKey("Use a Supabase secret key or legacy service_role key") from exc
    if claims.get("role") != "service_role":
        raise InvalidSupabaseKey("The configured legacy key is not a service_role key")
    headers["Authorization"] = f"Bearer {key}"
    return headers


@lru_cache(maxsize=4)
def create_data_api_client(url: str, key: str) -> SyncPostgrestClient:
    """Create a cached, server-only client for Supabase's PostgREST endpoint."""
    base_url = f"{url.rstrip('/')}/rest/v1"
    headers = _data_api_headers(key)
    http_client = httpx.Client(
        base_url=base_url,
        headers=headers,
        timeout=10,
        follow_redirects=True,
    )
    return SyncPostgrestClient(
        base_url,
        headers=headers,
        http_client=http_client,
    )


def database_error_detail(exc: Exception) -> str:
    """Return a useful but non-sensitive readiness error for known failures."""
    code = getattr(exc, "code", None)
    message = str(getattr(exc, "message", exc)).lower()
    if code in {"42P01", "42703", "42883", "PGRST202", "PGRST204", "PGRST205"}:
        return "Database schema is not initialized; run the Supabase migrations"
    if "could not find the table" in message:
        return "Database schema is not initialized; run the Supabase migrations"
    if code in {"PGRST301", "PGRST302"} or "invalid jwt" in message or "api key" in message:
        return "Supabase credentials were rejected"
    return "Database connection unavailable"
