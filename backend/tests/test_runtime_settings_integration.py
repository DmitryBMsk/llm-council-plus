"""Integration tests: runtime settings affect prompts + temperatures."""

from __future__ import annotations

import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_stage2_uses_runtime_prompt_template_and_temperature(monkeypatch):
    from ..council import stage2_collect_rankings
    from ..runtime_settings import RuntimeSettings

    captured = {}

    async def fake_query_models_with_stage_timeout(router_type, models, messages, **kwargs):
        # Capture the fully rendered prompt and the temperature passed down.
        # Stage 2 sends each judge its own prompt, keyed by model.
        captured["prompt"] = messages[models[0]][0]["content"]
        captured["temperature"] = kwargs.get("temperature")
        return {models[0]: {"content": "FINAL RANKING:\n1. Response A"}}

    monkeypatch.setattr(
        "backend.runtime_settings.get_runtime_settings",
        lambda: RuntimeSettings(
            stage2_prompt_template="CUSTOM\nQuestion: {user_query}\n\n{responses_text}",
            stage2_temperature=0.11,
        ),
    )

    with patch("backend.router_dispatch.query_models_with_stage_timeout", side_effect=fake_query_models_with_stage_timeout):
        stage2_results, label_to_model = await stage2_collect_rankings(
            "What is Python?",
            [{"model": "m1", "response": "Python is great."}],
            models=["m1"],
        )

    assert "CUSTOM" in captured["prompt"]
    assert "What is Python?" in captured["prompt"]
    assert captured["temperature"] == pytest.approx(0.11)
    assert stage2_results
    assert label_to_model


@pytest.mark.asyncio
async def test_stage1_applies_runtime_stage1_prompt_template(monkeypatch):
    from ..council import stage1_collect_responses_streaming
    from ..runtime_settings import RuntimeSettings

    seen = {"messages": None}

    async def fake_query_models_streaming(router_type, models, messages, **kwargs):
        seen["messages"] = messages
        if False:
            yield  # pragma: no cover

    monkeypatch.setattr(
        "backend.runtime_settings.get_runtime_settings",
        lambda: RuntimeSettings(stage1_prompt_template="PREFIX\n\n{full_query}"),
    )

    with patch("backend.router_dispatch.query_models_streaming", side_effect=fake_query_models_streaming):
        gen = stage1_collect_responses_streaming("Hello", conversation_history=None, models=["m1"])
        # Exhaust generator
        async for _ in gen:
            pass

    assert seen["messages"] is not None
    # Stage 1 base behavior is user message only; template should wrap it.
    user_msg = next(m for m in seen["messages"] if m["role"] == "user")
    assert "PREFIX" in user_msg["content"] if isinstance(user_msg["content"], str) else user_msg["content"][0]["text"]
