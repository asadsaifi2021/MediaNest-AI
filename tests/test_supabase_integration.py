"""Opt-in smoke test for a configured, migrated Supabase project."""

import os

import pytest

from app.config import get_settings
from app.database import create_data_api_client


@pytest.mark.skipif(
    os.getenv("RUN_SUPABASE_INTEGRATION") != "1",
    reason="set RUN_SUPABASE_INTEGRATION=1 to contact the configured Supabase project",
)
def test_live_supabase_data_api() -> None:
    settings = get_settings()
    assert settings.supabase_url is not None, "SUPABASE_URL is required"
    assert settings.supabase_secret_key is not None, "SUPABASE_SECRET_KEY is required"
    client = create_data_api_client(
        str(settings.supabase_url), settings.supabase_secret_key.get_secret_value()
    )
    response = client.table("media_metadata").select("id").limit(1).execute()
    assert isinstance(response.data, list)
