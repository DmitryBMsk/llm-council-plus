"""Tests for the curated free-model preset endpoint (shir-man.com/free-llm feed)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ..api.routes import models as models_mod


FEED = {
    "updatedAt": "2026-07-02T03:17:00.946Z",
    "primary": {"id": "nvidia/nemotron-3-super-120b-a12b:free"},
    "alternatives": [
        {"id": "cohere/north-mini-code:free"},
        {"id": "google/gemma-4-31b-it:free"},
        {"id": "nvidia/nemotron-3-super-120b-a12b:free"},  # duplicate of primary
    ],
}


@pytest.fixture(autouse=True)
def _reset_cache():
    models_mod._free_preset_cache["data"] = None
    models_mod._free_preset_cache["timestamp"] = 0.0
    yield
    models_mod._free_preset_cache["data"] = None
    models_mod._free_preset_cache["timestamp"] = 0.0


def test_extract_free_preset_primary_first_and_deduped():
    result = models_mod._extract_free_preset(FEED)
    assert result["models"] == [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "cohere/north-mini-code:free",
        "google/gemma-4-31b-it:free",
    ]
    assert result["chairman"] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert result["updated_at"] == "2026-07-02T03:17:00.946Z"


def test_extract_free_preset_handles_missing_primary():
    result = models_mod._extract_free_preset({"alternatives": [{"id": "a/b:free"}]})
    assert result["models"] == ["a/b:free"]
    assert result["chairman"] is None


@pytest.mark.asyncio
async def test_endpoint_returns_feed_and_caches():
    with patch.object(
        models_mod, "_fetch_free_recommendation", new=AsyncMock(return_value=FEED)
    ) as fetch:
        first = await models_mod.get_free_preset()
        second = await models_mod.get_free_preset()

    assert first["models"][0] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert second == first
    fetch.assert_awaited_once()  # second call served from cache


@pytest.mark.asyncio
async def test_endpoint_degrades_to_empty_when_feed_unavailable():
    with patch.object(
        models_mod,
        "_fetch_free_recommendation",
        new=AsyncMock(side_effect=RuntimeError("feed down")),
    ):
        result = await models_mod.get_free_preset()

    assert result["models"] == []
    assert result["chairman"] is None


@pytest.mark.asyncio
async def test_endpoint_serves_stale_cache_when_feed_breaks():
    with patch.object(
        models_mod, "_fetch_free_recommendation", new=AsyncMock(return_value=FEED)
    ):
        fresh = await models_mod.get_free_preset()

    # Expire the TTL, then break the feed — stale data must still be served.
    models_mod._free_preset_cache["timestamp"] = 0.0
    with patch.object(
        models_mod,
        "_fetch_free_recommendation",
        new=AsyncMock(side_effect=RuntimeError("feed down")),
    ):
        stale = await models_mod.get_free_preset()

    assert stale == fresh
