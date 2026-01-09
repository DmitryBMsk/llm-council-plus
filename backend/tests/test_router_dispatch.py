"""Tests for router dispatch layer (OpenRouter vs Ollama)."""

from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_dispatch_query_model_calls_openrouter(monkeypatch):
    from .. import router_dispatch
    from .. import openrouter

    spy = AsyncMock(return_value={"content": "ok"})
    monkeypatch.setattr(openrouter, "query_model", spy)

    result = await router_dispatch.query_model(
        "openrouter",
        model="openai/gpt-5.1",
        messages=[{"role": "user", "content": "hi"}],
        stage="STAGE1",
        temperature=0.2,
    )

    assert result == {"content": "ok"}
    spy.assert_awaited_once()
    _, kwargs = spy.call_args
    assert kwargs["model"] == "openai/gpt-5.1"
    assert kwargs["stage"] == "STAGE1"
    assert kwargs["temperature"] == 0.2


@pytest.mark.asyncio
async def test_dispatch_query_model_calls_ollama(monkeypatch):
    from .. import router_dispatch
    from .. import ollama

    spy = AsyncMock(return_value={"content": "ok"})
    monkeypatch.setattr(ollama, "query_model", spy)

    result = await router_dispatch.query_model(
        "ollama",
        model="llama3.1:latest",
        messages=[{"role": "user", "content": "hi"}],
        stage="STAGE1",  # should be ignored for ollama
        temperature=0.7,
    )

    assert result == {"content": "ok"}
    spy.assert_awaited_once()
    _, kwargs = spy.call_args
    assert kwargs["model"] == "llama3.1:latest"
    assert kwargs["temperature"] == 0.7
    assert "stage" not in kwargs


def test_dispatch_build_message_content_openrouter(monkeypatch):
    from .. import router_dispatch
    from .. import openrouter

    spy = Mock(side_effect=lambda text, images=None: [{"type": "text", "text": text}])
    monkeypatch.setattr(openrouter, "build_message_content", spy)

    content = router_dispatch.build_message_content(
        "openrouter",
        text="hello",
        images=[{"content": "data:image/png;base64,AAA", "filename": "x.png"}],
    )
    assert content == [{"type": "text", "text": "hello"}]


def test_dispatch_build_message_content_ollama_ignores_images():
    from .. import router_dispatch

    content = router_dispatch.build_message_content(
        "ollama",
        text="hello",
        images=[{"content": "data:image/png;base64,AAA", "filename": "x.png"}],
    )
    assert content == "hello"


def test_dispatch_rejects_unknown_router_type():
    from .. import router_dispatch

    with pytest.raises(ValueError):
        router_dispatch.build_message_content("hybrid", text="x", images=None)
