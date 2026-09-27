"""Supabase JWT and edge-device HMAC authentication dependencies."""

import hashlib
import hmac
import time
from functools import lru_cache
from typing import Annotated, Any

import httpx
import jwt
from anyio import to_thread
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidTokenError,
    PyJWKClientConnectionError,
    PyJWKClientError,
    PyJWKError,
)

from .config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


class IdentityProviderUnavailable(RuntimeError):
    """Raised when a token cannot be checked because Supabase Auth is unavailable."""


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache(maxsize=8)
def _cached_jwks_client(url: str, lifespan: int, timeout: float) -> PyJWKClient:
    # Cache the JWKS document, not individual keys forever, so rotation works.
    return PyJWKClient(
        url,
        cache_jwk_set=True,
        cache_keys=False,
        lifespan=lifespan,
        timeout=timeout,
    )


def get_jwks_client(settings: Settings) -> PyJWKClient:
    if settings.jwks_url is None:
        raise HTTPException(status_code=503, detail="JWT verification is not configured")
    return _cached_jwks_client(
        settings.jwks_url,
        settings.jwks_cache_lifespan_seconds,
        settings.jwks_request_timeout_seconds,
    )


def _decode_token(token: str, settings: Settings) -> dict[str, Any]:
    """Resolve an asymmetric signing key and decode a token."""
    signing_key = get_jwks_client(settings).get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256", "EdDSA"],
        audience=settings.supabase_jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["exp", "iat", "sub"]},
    )


def _validate_shared_secret_token(token: str, settings: Settings) -> dict[str, Any]:
    """Validate HS256 access tokens through Supabase Auth without exposing its secret."""
    if settings.supabase_url is None or settings.supabase_secret_key is None:
        raise IdentityProviderUnavailable("Shared-secret JWT verification is not configured")
    try:
        response = httpx.get(
            f"{str(settings.supabase_url).rstrip('/')}/auth/v1/user",
            headers={
                "apikey": settings.supabase_secret_key.get_secret_value(),
                "Authorization": f"Bearer {token}",
            },
            timeout=settings.jwks_request_timeout_seconds,
        )
    except httpx.RequestError as exc:
        raise IdentityProviderUnavailable("Unable to reach Supabase Auth") from exc
    if response.status_code != 200:
        raise InvalidTokenError("Supabase Auth rejected the token")

    claims = jwt.decode(
        token,
        options={
            "verify_signature": False,
            "verify_exp": True,
            "verify_iat": True,
            "verify_aud": True,
            "verify_iss": True,
            "require": ["exp", "iat", "sub"],
        },
        audience=settings.supabase_jwt_audience,
        issuer=settings.jwt_issuer,
    )
    if response.json().get("id") != claims["sub"]:
        raise InvalidTokenError("Authenticated user does not match the token subject")
    return claims


def _verify_token(token: str, settings: Settings) -> dict[str, Any]:
    algorithm = jwt.get_unverified_header(token).get("alg")
    if algorithm == "HS256":
        return _validate_shared_secret_token(token, settings)
    if algorithm not in {"RS256", "ES256", "EdDSA"}:
        raise InvalidTokenError("Unsupported JWT signing algorithm")
    return _decode_token(token, settings)


async def verify_supabase_jwt(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Missing bearer token")
    if settings.jwt_issuer is None:
        raise HTTPException(status_code=503, detail="JWT verification is not configured")
    try:
        return await to_thread.run_sync(_verify_token, credentials.credentials, settings)
    except ExpiredSignatureError as exc:
        raise _unauthorized("Token has expired") from exc
    except PyJWKClientConnectionError as exc:
        raise HTTPException(status_code=503, detail="Unable to reach the identity provider") from exc
    except IdentityProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail="Unable to reach the identity provider") from exc
    except (InvalidTokenError, PyJWKClientError, PyJWKError, ValueError) as exc:
        raise _unauthorized("Invalid bearer token") from exc


async def verify_edge_signature(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Verify HMAC-SHA256(secret, timestamp + '.' + exact request body)."""
    if settings.edge_hmac_secret is None:
        raise HTTPException(status_code=503, detail="Edge signature verification is not configured")
    timestamp_header = request.headers.get("X-Edge-Timestamp")
    supplied_signature = request.headers.get("X-Edge-Signature")
    if not timestamp_header or not supplied_signature:
        raise HTTPException(status_code=401, detail="Missing edge signature headers")
    try:
        signed_at = int(timestamp_header)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid edge timestamp") from exc
    if abs(int(time.time()) - signed_at) > settings.edge_signature_max_age_seconds:
        raise HTTPException(status_code=401, detail="Edge signature has expired")

    # Starlette caches body(); FastAPI can still validate the request model later.
    body = await request.body()
    expected = hmac.new(
        settings.edge_hmac_secret.get_secret_value().encode(),
        timestamp_header.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    candidate = supplied_signature.removeprefix("sha256=").lower()
    if not hmac.compare_digest(expected, candidate):
        raise HTTPException(status_code=401, detail="Invalid edge signature")


CurrentUser = Annotated[dict[str, Any], Depends(verify_supabase_jwt)]
