"""Stage 3 must not synthesize from an empty council (A0.2).

When every Stage 1 model fails, the error entries keep ``stage1_results``
non-empty so the existing ``if not stage1_results`` guard does not fire. The
response-filter then reduces the usable data to ``[]``; without a second guard
the chairman would be asked to synthesize a "final answer" from nothing.
"""
import pytest
from unittest.mock import AsyncMock, patch

from backend import council


@pytest.mark.asyncio
async def test_stage3_returns_error_when_all_stage1_responses_failed():
    # Entries are present but none carries a usable 'response'.
    stage1_results = [
        {"model": "openai/gpt-x", "error": "rate limited"},
        {"model": "anthropic/claude-x", "response": ""},
    ]

    with patch.object(council.router_dispatch, "query_model", new=AsyncMock()) as mock_query:
        result = await council.stage3_synthesize_final(
            user_query="What is 2+2?",
            stage1_results=stage1_results,
            stage2_results=[],
            chairman="openai/gpt-x",
        )

    assert result.get("error") is True
    assert "No model responses" in result["response"]
    # Guard must short-circuit before the chairman is ever queried.
    mock_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_stage3_proceeds_when_at_least_one_response_present():
    # A single usable response must NOT trip the empty guard.
    stage1_results = [
        {"model": "m1", "error": "boom"},
        {"model": "m2", "response": "4"},
    ]
    fake = {"model": "m2", "response": "Final answer: 4", "error": False}

    with patch.object(
        council.router_dispatch, "query_model", new=AsyncMock(return_value=fake)
    ) as mock_query:
        result = await council.stage3_synthesize_final(
            user_query="What is 2+2?",
            stage1_results=stage1_results,
            stage2_results=[],
            chairman="m2",
        )

    assert mock_query.await_count >= 1
    assert "response" in result
