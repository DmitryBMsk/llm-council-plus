"""Tests that council stages route via router_dispatch using router_type."""

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_stage1_uses_router_type_for_parallel_calls(monkeypatch):
    from .. import council
    from .. import router_dispatch

    spy = AsyncMock(return_value={"m1": {"content": "ok"}})
    monkeypatch.setattr(router_dispatch, "query_models_parallel", spy)

    # Avoid tools/memory paths in stage1
    monkeypatch.setattr(council, "requires_tools", lambda *_: False)
    monkeypatch.setattr(council.config, "ENABLE_MEMORY", False)

    await council.stage1_collect_responses(
        "hello",
        conversation_history=[],
        models=["m1"],
        images=None,
        conversation_id=None,
        router_type="ollama",
    )

    spy.assert_awaited_once()
    args, _ = spy.call_args
    assert args[0] == "ollama"


@pytest.mark.asyncio
async def test_stage1_streaming_uses_router_type(monkeypatch):
    from .. import council
    from .. import router_dispatch

    called = {"router_type": None}

    async def fake_streaming(*args, **kwargs):
        # args: (router_type, models, messages)
        called["router_type"] = args[0] if args else None
        yield ("m1", {"content": "ok"})

    monkeypatch.setattr(router_dispatch, "query_models_streaming", fake_streaming)

    monkeypatch.setattr(council, "requires_tools", lambda *_: False)
    monkeypatch.setattr(council.config, "ENABLE_MEMORY", False)

    items = []
    async for item in council.stage1_collect_responses_streaming(
        "hello",
        conversation_history=[],
        models=["m1"],
        images=None,
        conversation_id=None,
        chairman=None,
        router_type="openrouter",
    ):
        items.append(item)

    assert items, "Expected at least one streamed item"
    assert called["router_type"] == "openrouter"


def test_build_multimodal_messages_ollama_ignores_images():
    from .. import council

    messages = council.build_multimodal_messages(
        "describe this",
        images=[{"content": "data:image/png;base64,AAA", "filename": "x.png"}],
        conversation_history=[],
        router_type="ollama",
    )

    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "describe this"


@pytest.mark.asyncio
async def test_stage2_uses_router_type_for_timeout_batch(monkeypatch):
    from .. import council
    from .. import router_dispatch

    spy = AsyncMock(return_value={"m1": {"content": "FINAL RANKING:\n1. Response A"}})
    monkeypatch.setattr(router_dispatch, "query_models_with_stage_timeout", spy)

    stage1_results = [{"model": "m1", "response": "Answer"}]
    rankings, _ = await council.stage2_collect_rankings(
        "question",
        stage1_results,
        models=["m1"],
        router_type="ollama",
    )

    assert rankings, "Expected at least one ranking"
    spy.assert_awaited_once()
    assert spy.call_args.args[0] == "ollama"


@pytest.mark.asyncio
async def test_stage3_uses_router_type_for_chairman(monkeypatch):
    from .. import council
    from .. import router_dispatch

    spy = AsyncMock(return_value={"content": "Final answer"})
    monkeypatch.setattr(router_dispatch, "query_model", spy)

    stage1_results = [{"model": "m1", "response": "Answer"}]
    stage2_results = [{"model": "m1", "ranking": "FINAL RANKING:\n1. Response A"}]
    result = await council.stage3_synthesize_final(
        "question",
        stage1_results,
        stage2_results,
        chairman="m1",
        tool_outputs=None,
        router_type="openrouter",
    )

    assert result["response"] == "Final answer"
    spy.assert_awaited_once()
    assert spy.call_args.args[0] == "openrouter"
