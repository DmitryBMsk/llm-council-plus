"""API tests for per-conversation router_type."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_api_create_conversation_passes_router_type_to_storage():
    """
    create_conversation API should pass router_type through to storage so it can be
    persisted and used later by streaming endpoints.
    """
    from ..main import create_conversation as api_create_conversation
    from .. import storage

    def fake_create(*args, **kwargs):
        return {
            "id": args[0],
            "created_at": "now",
            "title": "New Conversation",
            "messages": [],
            "models": kwargs.get("models"),
            "chairman": kwargs.get("chairman"),
            "username": kwargs.get("username"),
            "execution_mode": kwargs.get("execution_mode"),
            "router_type": kwargs.get("router_type"),
        }

    with patch.object(storage, "create_conversation", side_effect=fake_create) as spy:

        class MockRequest:
            models = None
            chairman = None
            username = None
            execution_mode = "full"
            router_type = "ollama"
            system_prompt = None

        conv = await api_create_conversation(MockRequest(), current_user="guest")

    assert conv["router_type"] == "ollama"
    _, kwargs = spy.call_args
    assert kwargs.get("router_type") == "ollama"


@pytest.mark.asyncio
async def test_send_message_stream_passes_router_type_to_council():
    """
    send_message_stream should pass the conversation's router_type down into the council
    stage runners so each stage queries the intended router.
    """
    from ..main import send_message_stream
    from .. import storage

    conversation_id = "00000000-0000-0000-0000-000000000210"
    saved_messages = []

    async def mock_stage1_streaming(*args, **kwargs):
        yield {"model": "m1", "response": "r1"}

    async def stage2_collect_rankings_spy(*args, **kwargs):
        # For this test we don't care about actual results; we care about router_type.
        assert kwargs.get("router_type") == "ollama"
        return ([], {})

    async def stage3_synthesize_final_spy(*args, **kwargs):
        assert kwargs.get("router_type") == "ollama"
        return {"model": "m1", "response": "final"}

    def track_save(*args, **kwargs):
        saved_messages.append({"args": args, "kwargs": kwargs})

    with patch.object(
        storage,
        "get_conversation",
        return_value={
            "id": conversation_id,
            "messages": [],
            "models": None,
            "chairman": None,
            "execution_mode": "full",
            "router_type": "ollama",
        },
    ), patch.object(storage, "add_user_message"), patch.object(
        storage, "add_assistant_message", side_effect=track_save
    ), patch.object(storage, "update_conversation_title"), patch(
        "backend.api.routes.conversations.generate_conversation_title", autospec=True
    ) as title_gen_mock, patch(
        "backend.api.routes.conversations.stage1_collect_responses_streaming", mock_stage1_streaming
    ), patch(
        "backend.api.routes.conversations.stage2_collect_rankings", stage2_collect_rankings_spy
    ), patch(
        "backend.api.routes.conversations.stage3_synthesize_final", stage3_synthesize_final_spy
    ):
        title_gen_mock.return_value = "Title"

        class MockRequest:
            content = "Test query"
            attachments = None
            web_search = False
            web_search_provider = None

        response = await send_message_stream(conversation_id, MockRequest(), current_user="guest")

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

    joined = b"".join(c if isinstance(c, (bytes, bytearray)) else str(c).encode() for c in chunks)
    assert b"stage1_start" in joined
    assert b"stage2_start" in joined
    assert b"stage3_start" in joined
    assert b"complete" in joined
    assert saved_messages, "Expected at least one save"

