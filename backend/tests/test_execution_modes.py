"""Tests for conversation-level execution modes (chat_only/chat_ranking/full)."""

from unittest.mock import patch, AsyncMock
import pytest


def test_storage_add_assistant_message_allows_stage_omission_for_chat_only():
    """
    In chat_only mode, we should be able to store an assistant message that contains
    only Stage 1 (and optional metadata), without requiring stage2/stage3.
    """
    from .. import storage

    conversation_id = "00000000-0000-0000-0000-000000000001"
    conversation = {"id": conversation_id, "messages": []}
    saved = []

    def save_spy(conv):
        saved.append(conv)

    with patch.object(storage, "get_conversation", return_value=conversation), patch.object(
        storage, "save_conversation", side_effect=save_spy
    ):
        storage.add_assistant_message(
            conversation_id,
            stage1=[{"model": "m1", "response": "r1"}],
            stage2=None,
            stage3=None,
            metadata={"execution_mode": "chat_only"},
        )

    assert saved, "Expected conversation to be saved"
    msg = saved[0]["messages"][-1]
    assert msg["role"] == "assistant"
    assert msg["stage1"] == [{"model": "m1", "response": "r1"}]
    assert "stage2" not in msg
    assert "stage3" not in msg
    assert msg["metadata"]["execution_mode"] == "chat_only"


def test_storage_add_assistant_message_allows_stage3_omission_for_chat_ranking():
    """
    In chat_ranking mode, we should store stage1 + stage2, and omit stage3.
    """
    from .. import storage

    conversation_id = "00000000-0000-0000-0000-000000000002"
    conversation = {"id": conversation_id, "messages": []}
    saved = []

    def save_spy(conv):
        saved.append(conv)

    with patch.object(storage, "get_conversation", return_value=conversation), patch.object(
        storage, "save_conversation", side_effect=save_spy
    ):
        storage.add_assistant_message(
            conversation_id,
            stage1=[{"model": "m1", "response": "r1"}],
            stage2=[{"model": "m1", "ranking": "1. Response A"}],
            stage3=None,
            metadata={"execution_mode": "chat_ranking"},
        )

    msg = saved[0]["messages"][-1]
    assert msg["stage1"]
    assert msg["stage2"] == [{"model": "m1", "ranking": "1. Response A"}]
    assert "stage3" not in msg


def test_create_conversation_persists_execution_mode_in_json_storage(tmp_path, monkeypatch):
    """
    execution_mode is a conversation-level default, so it must be persisted in storage.

    Backwards compatibility requirement: old conversations won't have this field, so
    it must be optional on read and default to "full" in code paths that use it.
    """
    from .. import storage

    monkeypatch.setattr(storage.config, "DATA_DIR", str(tmp_path))

    conversation_id = "00000000-0000-0000-0000-000000000010"
    created = storage.create_conversation(
        conversation_id,
        models=None,
        chairman=None,
        username=None,
        execution_mode="chat_only",
    )

    assert created["execution_mode"] == "chat_only"

    loaded = storage.get_conversation(conversation_id)
    assert loaded is not None
    assert loaded["execution_mode"] == "chat_only"


@pytest.mark.asyncio
async def test_stream_chat_only_skips_stage2_and_stage3():
    """
    When a conversation is configured with execution_mode='chat_only', the SSE pipeline
    should run Stage 1 only and never call Stage 2/Stage 3.
    """
    from ..main import send_message_stream
    from .. import storage

    conversation_id = "00000000-0000-0000-0000-000000000003"
    saved_messages = []

    async def mock_stage1_streaming(*args, **kwargs):
        yield {"model": "m1", "response": "r1"}

    async def stage2_should_not_run(*args, **kwargs):
        raise AssertionError("Stage 2 should not run in chat_only mode")

    async def stage3_should_not_run(*args, **kwargs):
        raise AssertionError("Stage 3 should not run in chat_only mode")

    def track_save(*args, **kwargs):
        saved_messages.append({"args": args, "kwargs": kwargs})

    with patch.object(storage, "get_conversation", return_value={
        "id": conversation_id,
        "messages": [],
        "models": None,
        "chairman": None,
        "execution_mode": "chat_only",
    }), patch.object(storage, "add_user_message"), patch.object(
        storage, "add_assistant_message", side_effect=track_save
    ), patch.object(storage, "update_conversation_title"), patch(
        "backend.main.generate_conversation_title", new=AsyncMock(return_value="Test Title")
    ), patch("backend.main.stage1_collect_responses_streaming", mock_stage1_streaming), patch(
        "backend.main.stage2_collect_rankings", stage2_should_not_run
    ), patch("backend.main.stage3_synthesize_final", stage3_should_not_run):

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
    assert b"stage1_complete" in joined
    assert b"stage2_start" not in joined
    assert b"stage3_start" not in joined
    assert b"complete" in joined

    assert len(saved_messages) == 1, "Should save exactly once"
    saved_call = saved_messages[0]["args"]
    # args: (conversation_id, stage1, stage2?, stage3?, metadata?)
    assert saved_call[0] == conversation_id
    assert saved_call[1] == [{"model": "m1", "response": "r1"}]
    # In chat_only we expect stage2/stage3 omitted entirely (default None)
    assert len(saved_call) >= 2


@pytest.mark.asyncio
async def test_api_create_conversation_passes_execution_mode_to_storage():
    """
    Conversation-level execution_mode must be persisted at creation time so that
    subsequent messages can use the configured mode.
    """
    from ..main import create_conversation as api_create_conversation
    from .. import storage

    def fake_create(*args, **kwargs):
        # Return the same shape the API expects.
        return {
            "id": args[0],
            "created_at": "now",
            "title": "New Conversation",
            "messages": [],
            "models": kwargs.get("models"),
            "chairman": kwargs.get("chairman"),
            "username": kwargs.get("username"),
            "execution_mode": kwargs.get("execution_mode"),
        }

    with patch.object(storage, "create_conversation", side_effect=fake_create) as spy:

        class MockRequest:
            models = None
            chairman = None
            username = None
            execution_mode = "chat_only"

        conv = await api_create_conversation(MockRequest(), current_user="guest")

    assert conv["execution_mode"] == "chat_only"
    _, kwargs = spy.call_args
    assert kwargs.get("execution_mode") == "chat_only"
