"""Tests for conversation-level execution modes (chat_only/chat_ranking/full)."""

import asyncio
import json
from unittest.mock import patch, AsyncMock
import pytest


def _parse_sse_event(chunk):
    """Decode a single SSE chunk emitted by the streaming endpoint."""
    text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else str(chunk)
    assert text.startswith("data: "), text
    return json.loads(text[6:].strip())


async def _collect_sse_events(response):
    """Collect decoded SSE payloads from a StreamingResponse."""
    events = []
    async for chunk in response.body_iterator:
        events.append(_parse_sse_event(chunk))
    return events


class _ControlledTask:
    """Small deterministic task double for heartbeat tests."""

    def __init__(self, result, *, timeouts_before_done=0):
        self._result = result
        self._timeouts_before_done = timeouts_before_done
        self.cancelled = False

    def done(self):
        return self._timeouts_before_done == 0

    def result(self):
        return self._result

    def cancel(self):
        self.cancelled = True
        self._timeouts_before_done = 0

    async def wait(self):
        return self._result


def test_storage_add_assistant_message_allows_stage_omission_for_chat_only():
    """
    In chat_only mode, we should be able to store an assistant message that contains
    only Stage 1 (and optional metadata), without requiring stage2/stage3.
    """
    from .. import storage

    conversation_id = "00000000-0000-0000-0000-000000000001"
    conversation = {"id": conversation_id, "messages": []}
    saved = []

    def update_spy(cid, update_fn):
        assert cid == conversation_id
        update_fn(conversation)
        saved.append(conversation)
        return conversation

    with patch.object(storage, "is_using_database", return_value=False), patch.object(
        storage, "_json_update_conversation", side_effect=update_spy
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

    def update_spy(cid, update_fn):
        assert cid == conversation_id
        update_fn(conversation)
        saved.append(conversation)
        return conversation

    with patch.object(storage, "is_using_database", return_value=False), patch.object(
        storage, "_json_update_conversation", side_effect=update_spy
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
        "backend.api.routes.conversations.generate_conversation_title", new=AsyncMock(return_value="Test Title")
    ), patch("backend.api.routes.conversations.stage1_collect_responses_streaming", mock_stage1_streaming), patch(
        "backend.api.routes.conversations.stage2_collect_rankings", stage2_should_not_run
    ), patch("backend.api.routes.conversations.stage3_synthesize_final", stage3_should_not_run):

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
async def test_stream_chat_only_emits_tool_outputs_token_stats_and_title_for_first_message():
    """chat_only should stop after Stage 1 but still emit the rest of the visible contract."""
    from ..main import send_message_stream
    from .. import storage

    conversation_id = "00000000-0000-0000-0000-000000000004"
    saved_messages = []
    tool_outputs = [{"type": "web_search", "content": "search hit"}]
    token_stats = {"total": 42, "input": 12, "output": 30}

    async def mock_stage1_streaming(*args, **kwargs):
        yield {"type": "tool_outputs", "tool_outputs": tool_outputs}
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
        "backend.api.routes.conversations.generate_conversation_title", new=AsyncMock(return_value="Generated Title")
    ), patch("backend.api.routes.conversations.stage1_collect_responses_streaming", mock_stage1_streaming), patch(
        "backend.api.routes.conversations.stage2_collect_rankings", stage2_should_not_run
    ), patch("backend.api.routes.conversations.stage3_synthesize_final", stage3_should_not_run), patch(
        "backend.api.routes.conversations.get_token_stats", return_value=token_stats
    ), patch("backend.api.routes.conversations.reset_token_stats"):

        class MockRequest:
            content = "First message"
            attachments = None
            web_search = False
            web_search_provider = None

        response = await send_message_stream(conversation_id, MockRequest(), current_user="guest")
        events = await _collect_sse_events(response)

    assert [event["type"] for event in events] == [
        "stage1_start",
        "tool_outputs",
        "stage1_model_response",
        "stage1_complete",
        "token_stats",
        "title_complete",
        "complete",
    ]
    assert events[1]["data"] == tool_outputs
    assert events[4]["data"] == token_stats
    assert events[5]["data"] == {"title": "Generated Title"}

    assert len(saved_messages) == 1
    saved_call = saved_messages[0]["args"]
    assert saved_call[4] == {
        "execution_mode": "chat_only",
        "tool_outputs": tool_outputs,
        "token_stats": token_stats,
    }


@pytest.mark.asyncio
async def test_stream_chat_ranking_stops_after_stage2_with_heartbeat_and_metadata():
    """chat_ranking should emit a Stage 2 heartbeat and never enter Stage 3."""
    from ..main import send_message_stream
    from .. import storage

    conversation_id = "00000000-0000-0000-0000-000000000005"
    saved_messages = []
    tool_outputs = [{"type": "calculator", "content": "2+2=4"}]
    stage2_results = [{"model": "judge-1", "ranking": "1. Response A"}]
    label_to_model = {"Response A": "m1"}
    aggregate_rankings = [{"response": "Response A", "score": 1.0}]
    token_stats = {"total": 12, "input": 7, "output": 5}
    stage2_task = _ControlledTask((stage2_results, label_to_model), timeouts_before_done=1)

    async def mock_stage1_streaming(*args, **kwargs):
        yield {"type": "tool_outputs", "tool_outputs": tool_outputs}
        yield {"model": "m1", "response": "r1"}

    async def stage3_should_not_run(*args, **kwargs):
        raise AssertionError("Stage 3 should not run in chat_ranking mode")

    def track_save(*args, **kwargs):
        saved_messages.append({"args": args, "kwargs": kwargs})

    def fake_create_task(coro):
        coro.close()
        return stage2_task

    def fake_shield(task):
        return task

    async def fake_wait_for(task, timeout):
        if task._timeouts_before_done > 0:
            task._timeouts_before_done -= 1
            raise asyncio.TimeoutError
        return task.result()

    with patch.object(storage, "get_conversation", return_value={
        "id": conversation_id,
        "messages": [{"role": "user", "content": "Existing message"}],
        "models": None,
        "chairman": None,
        "execution_mode": "chat_ranking",
    }), patch.object(storage, "add_user_message"), patch.object(
        storage, "add_assistant_message", side_effect=track_save
    ), patch.object(storage, "update_conversation_title"), patch(
        "backend.api.routes.conversations.stage1_collect_responses_streaming", mock_stage1_streaming
    ), patch("backend.api.routes.conversations.stage3_synthesize_final", stage3_should_not_run), patch(
        "backend.api.routes.conversations.calculate_aggregate_rankings", return_value=aggregate_rankings
    ), patch("backend.api.routes.conversations.get_token_stats", return_value=token_stats), patch(
        "backend.api.routes.conversations.reset_token_stats"
    ), patch("backend.api.routes.conversations.asyncio.create_task", side_effect=fake_create_task), patch(
        "backend.api.routes.conversations.asyncio.shield", side_effect=fake_shield
    ), patch("backend.api.routes.conversations.asyncio.wait_for", side_effect=fake_wait_for):

        class MockRequest:
            content = "Rank this"
            attachments = None
            web_search = False
            web_search_provider = None

        response = await send_message_stream(conversation_id, MockRequest(), current_user="guest")
        events = await _collect_sse_events(response)

    assert [event["type"] for event in events] == [
        "stage1_start",
        "tool_outputs",
        "stage1_model_response",
        "stage1_complete",
        "stage2_start",
        "heartbeat",
        "stage2_complete",
        "token_stats",
        "complete",
    ]
    assert events[5]["stage"] == "stage2"
    assert events[6]["metadata"] == {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
    }
    assert "stage3_start" not in {event["type"] for event in events}

    assert len(saved_messages) == 1
    saved_call = saved_messages[0]["args"]
    assert saved_call[3] is None
    assert saved_call[4] == {
        "execution_mode": "chat_ranking",
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
        "tool_outputs": tool_outputs,
        "token_stats": token_stats,
    }


@pytest.mark.asyncio
async def test_stream_full_mode_emits_stage3_heartbeat_and_stage3_complete():
    """full mode should continue through Stage 3 and surface the Stage 3 heartbeat contract."""
    from ..main import send_message_stream
    from .. import storage

    conversation_id = "00000000-0000-0000-0000-000000000006"
    saved_messages = []
    stage2_results = [{"model": "judge-1", "ranking": "1. Response A"}]
    label_to_model = {"Response A": "m1"}
    aggregate_rankings = [{"response": "Response A", "score": 1.0}]
    stage3_result = {"model": "chairman", "response": "Final answer"}
    token_stats = {"total": 20, "input": 9, "output": 11}
    stage2_task = _ControlledTask((stage2_results, label_to_model))
    stage3_task = _ControlledTask(stage3_result, timeouts_before_done=1)
    created_tasks = []

    async def mock_stage1_streaming(*args, **kwargs):
        yield {"model": "m1", "response": "r1"}

    def track_save(*args, **kwargs):
        saved_messages.append({"args": args, "kwargs": kwargs})

    def fake_create_task(coro):
        coro.close()
        task = stage2_task if not created_tasks else stage3_task
        created_tasks.append(task)
        return task

    def fake_shield(task):
        return task

    async def fake_wait_for(task, timeout):
        if task._timeouts_before_done > 0:
            task._timeouts_before_done -= 1
            raise asyncio.TimeoutError
        return task.result()

    with patch.object(storage, "get_conversation", return_value={
        "id": conversation_id,
        "messages": [{"role": "user", "content": "Existing message"}],
        "models": None,
        "chairman": None,
        "execution_mode": "full",
    }), patch.object(storage, "add_user_message"), patch.object(
        storage, "add_assistant_message", side_effect=track_save
    ), patch.object(storage, "update_conversation_title"), patch(
        "backend.api.routes.conversations.stage1_collect_responses_streaming", mock_stage1_streaming
    ), patch("backend.api.routes.conversations.calculate_aggregate_rankings", return_value=aggregate_rankings), patch(
        "backend.api.routes.conversations.get_token_stats", return_value=token_stats
    ), patch("backend.api.routes.conversations.reset_token_stats"), patch(
        "backend.api.routes.conversations.asyncio.create_task", side_effect=fake_create_task
    ), patch("backend.api.routes.conversations.asyncio.shield", side_effect=fake_shield), patch(
        "backend.api.routes.conversations.asyncio.wait_for", side_effect=fake_wait_for
    ):

        class MockRequest:
            content = "Full run"
            attachments = None
            web_search = False
            web_search_provider = None

        response = await send_message_stream(conversation_id, MockRequest(), current_user="guest")
        events = await _collect_sse_events(response)

    assert [event["type"] for event in events] == [
        "stage1_start",
        "stage1_model_response",
        "stage1_complete",
        "stage2_start",
        "stage2_complete",
        "stage3_start",
        "heartbeat",
        "stage3_complete",
        "token_stats",
        "complete",
    ]
    assert events[6]["stage"] == "stage3"
    assert events[7]["data"] == stage3_result
    assert events[8]["data"] == token_stats

    assert len(saved_messages) == 1
    saved_call = saved_messages[0]["args"]
    assert saved_call[3] == stage3_result
    assert saved_call[4] == {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
        "tool_outputs": [],
        "token_stats": token_stats,
    }


@pytest.mark.asyncio
async def test_full_mode_first_message_emits_title_complete():
    """First message in full mode must emit title_complete SSE event.

    Regression test: double-brace typo {{'title': title}} caused TypeError.
    """
    from ..api.routes.conversations import send_message_stream
    from .. import storage

    conversation_id = "00000000-0000-0000-0000-000000000099"

    stage1_results = [{"model": "test/model-a", "response": "Answer A"}]
    stage2_results = [{"model": "test/model-a", "ranking": "1. A", "parsed_ranking": ["A"]}]
    stage3_result = {"response": "Final answer"}
    label_to_model = {"Response A": "test/model-a"}
    aggregate_rankings = [{"model": "test/model-a", "avg_position": 1.0}]
    token_stats = {"total": 100}

    saved_messages = []

    def track_save(*args, **kwargs):
        saved_messages.append({"args": args, "kwargs": kwargs})

    async def mock_stage1_streaming(*args, **kw):
        for r in stage1_results:
            yield r  # streaming yields dicts directly, not tuples

    stage2_task = asyncio.Future()
    stage2_task.set_result((stage2_results, label_to_model))
    stage2_task._timeouts_before_done = 0

    stage3_task = asyncio.Future()
    stage3_task.set_result(stage3_result)
    stage3_task._timeouts_before_done = 0

    title_task = asyncio.Future()
    title_task.set_result("Generated Title")

    created_tasks = []

    def fake_create_task(coro):
        if not created_tasks:
            task = title_task  # first create_task is title generation
        elif len(created_tasks) == 1:
            task = stage2_task
        else:
            task = stage3_task
        created_tasks.append(task)
        return task

    def fake_shield(task):
        return task

    async def fake_wait_for(task, timeout):
        if hasattr(task, '_timeouts_before_done') and task._timeouts_before_done > 0:
            task._timeouts_before_done -= 1
            raise asyncio.TimeoutError
        return task.result()

    # Key: empty messages list → is_first_message = True → title_task fires
    with patch.object(storage, "get_conversation", return_value={
        "id": conversation_id,
        "messages": [],
        "models": None,
        "chairman": None,
        "execution_mode": "full",
    }), patch.object(storage, "add_user_message"), patch.object(
        storage, "add_assistant_message", side_effect=track_save
    ), patch.object(storage, "update_conversation_title"), patch(
        "backend.api.routes.conversations.stage1_collect_responses_streaming", mock_stage1_streaming
    ), patch("backend.api.routes.conversations.calculate_aggregate_rankings", return_value=aggregate_rankings), patch(
        "backend.api.routes.conversations.get_token_stats", return_value=token_stats
    ), patch("backend.api.routes.conversations.reset_token_stats"), patch(
        "backend.api.routes.conversations.asyncio.create_task", side_effect=fake_create_task
    ), patch("backend.api.routes.conversations.asyncio.shield", side_effect=fake_shield), patch(
        "backend.api.routes.conversations.asyncio.wait_for", side_effect=fake_wait_for
    ):

        class MockRequest:
            content = "First message"
            attachments = None
            web_search = False
            web_search_provider = None

        response = await send_message_stream(conversation_id, MockRequest(), current_user="guest")
        events = await _collect_sse_events(response)

    event_types = [e["type"] for e in events]
    assert "title_complete" in event_types, f"title_complete missing from SSE events: {event_types}"
    assert "error" not in event_types, f"Unexpected error in SSE events: {event_types}"

    title_event = next(e for e in events if e["type"] == "title_complete")
    assert title_event["data"] == {"title": "Generated Title"}


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
