from __future__ import annotations

import jwt
import pytest

from app.database import (
    InvalidSupabaseKey,
    _data_api_headers,
    create_data_api_client,
    database_error_detail,
)


def test_modern_secret_key_is_never_sent_as_bearer_token() -> None:
    headers = _data_api_headers("sb_secret_server-only")
    assert headers["apikey"] == "sb_secret_server-only"
    assert "Authorization" not in headers


def test_legacy_service_role_key_is_sent_as_bearer_token() -> None:
    key = jwt.encode({"role": "service_role"}, "test-secret-at-least-32-bytes-long", algorithm="HS256")
    headers = _data_api_headers(key)
    assert headers["apikey"] == key
    assert headers["Authorization"] == f"Bearer {key}"


@pytest.mark.parametrize(
    "key",
    [
        "sb_publishable_browser-key",
        jwt.encode({"role": "anon"}, "test-secret-at-least-32-bytes-long", algorithm="HS256"),
        "not-a-supabase-key",
    ],
)
def test_public_or_invalid_server_keys_are_rejected(key: str) -> None:
    with pytest.raises(InvalidSupabaseKey):
        _data_api_headers(key)


def test_data_api_client_uses_only_apikey_for_modern_secret() -> None:
    create_data_api_client.cache_clear()
    client = create_data_api_client("https://project.supabase.co", "sb_secret_server-only")
    assert client.session.headers["apikey"] == "sb_secret_server-only"
    assert "authorization" not in client.session.headers


def test_missing_table_error_has_actionable_detail() -> None:
    error = RuntimeError("Could not find the table public.media_metadata in the schema cache")
    assert database_error_detail(error) == (
        "Database schema is not initialized; run the Supabase migrations"
    )
