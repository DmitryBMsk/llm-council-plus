"""Regression tests for batch 4 fixes.

- parse_ranking_from_text: case-insensitive header, dedup, no fabricated
  fallback ranking scraped from evaluation text.
- TOON token stats must be visible to the parent when recorded inside
  asyncio.create_task (Stage 2/3 run in child tasks).
- Stage 3 chairman fallback chain must be capped, not try every model.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend import council


# ---------------------------------------------------------------------------
# parse_ranking_from_text
# ---------------------------------------------------------------------------

def test_parse_ranking_uppercase_header():
    text = "Evaluation...\n\nFINAL RANKING:\n1. Response C\n2. Response A\n3. Response B"
    assert council.parse_ranking_from_text(text) == [
        "Response C", "Response A", "Response B"
    ]


def test_parse_ranking_header_is_case_insensitive():
    text = "Evaluation...\n\nFinal Ranking:\n1. Response B\n2. Response A"
    assert council.parse_ranking_from_text(text) == ["Response B", "Response A"]


def test_parse_ranking_dedupes_repeated_labels():
    text = "FINAL RANKING:\n1. Response A\n2. Response A\n3. Response B"
    assert council.parse_ranking_from_text(text) == ["Response A", "Response B"]


def test_parse_ranking_returns_empty_without_header():
    # The evaluation text mentions responses in discussion order; scraping it
    # would fabricate a ranking that mirrors Stage 1 order.
    text = (
        "Response A is thorough. Response B is concise but Response A cites "
        "sources. Response C is weakest."
    )
    assert council.parse_ranking_from_text(text) == []


# ---------------------------------------------------------------------------
# Token stats across task boundaries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_stats_recorded_in_child_task_visible_to_parent():
    council.reset_token_stats()

    async def child():
        # Simulates Stage 2/3 running inside asyncio.create_task with a
        # copied contextvars context.
        council.format_with_toon([{"model": "m1", "response": "hello"}], "stage2")

    await asyncio.create_task(child())

    stats = council.get_token_stats()
    assert stats["stage2"] is not None, "stats recorded in a child task must reach the parent"
    assert stats["total"] is not None


# ---------------------------------------------------------------------------
# Stage 3 fallback cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stage3_fallback_chain_is_capped():
    stage1_results = [
        {"model": f"org/m{i}", "response": f"answer {i}"} for i in range(6)
    ]
    failure = {"error": True, "error_message": "rate limited", "content": None}

    with patch.object(
        council.router_dispatch, "query_model", new=AsyncMock(return_value=failure)
    ) as mock_query:
        result = await council.stage3_synthesize_final(
            user_query="What is 2+2?",
            stage1_results=stage1_results,
            stage2_results=[],
            chairman="org/chairman",
        )

    assert result.get("error") is True
    # 1 chairman attempt + at most MAX_CHAIRMAN_FALLBACKS fallbacks — not all 6.
    assert mock_query.await_count == 1 + council.MAX_CHAIRMAN_FALLBACKS
