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
    for table, columns in (("archive_events", "id"), ("face_embeddings", "id,model_id")):
        assert isinstance(client.table(table).select(columns).limit(1).execute().data, list)
    response = client.rpc("match_faces_v2", {
        "query_embedding": [1.0] + [0.0] * 511,
        "match_threshold": 1.0, "match_count": 1,
        "p_user_id": "00000000-0000-0000-0000-000000000000",
    }).execute()
    assert isinstance(response.data, list)
