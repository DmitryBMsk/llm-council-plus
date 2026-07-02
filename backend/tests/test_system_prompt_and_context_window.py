"""Regression tests for batch 3 fixes.

- Custom system prompt must flow end-to-end: request model -> storage -> stage1.
- build_context_prompt must window unbounded conversation history.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Custom system prompt wiring (was silently dropped at the route layer)
# ---------------------------------------------------------------------------

def test_create_conversation_request_accepts_system_prompt():
    from ..main import CreateConversationRequest

    req = CreateConversationRequest(system_prompt="Answer like a pirate")
    assert req.system_prompt == "Answer like a pirate"


@pytest.mark.asyncio
async def test_api_create_conversation_passes_system_prompt_to_storage():
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
            "system_prompt": kwargs.get("system_prompt"),
        }

    with patch.object(storage, "create_conversation", side_effect=fake_create) as spy:

        class MockRequest:
            models = None
            chairman = None
            username = None
            execution_mode = "full"
            router_type = None
            system_prompt = "Answer like a pirate"

        conv = await api_create_conversation(MockRequest(), current_user="guest")

    assert conv["system_prompt"] == "Answer like a pirate"
    _, kwargs = spy.call_args
    assert kwargs.get("system_prompt") == "Answer like a pirate"


@pytest.mark.asyncio
async def test_send_message_stream_passes_system_prompt_to_stage1():
    from ..main import send_message_stream
    from .. import storage

    conversation_id = "00000000-0000-0000-0000-000000000310"
    seen_kwargs = {}

    async def mock_stage1_streaming(*args, **kwargs):
        seen_kwargs.update(kwargs)
        yield {"model": "m1", "response": "r1"}

    with patch.object(
        storage,
        "get_conversation",
        return_value={
            "id": conversation_id,
            "messages": [],
            "models": None,
            "chairman": None,
            "execution_mode": "chat_only",
            "router_type": None,
            "system_prompt": "Answer like a pirate",
        },
    ), patch.object(storage, "add_user_message"), patch.object(
        storage, "add_assistant_message"
    ), patch.object(storage, "update_conversation_title"), patch(
        "backend.api.routes.conversations.generate_conversation_title", autospec=True
    ) as title_gen_mock, patch(
        "backend.api.routes.conversations.stage1_collect_responses_streaming", mock_stage1_streaming
    ):
        title_gen_mock.return_value = "Title"

        class MockRequest:
            content = "Test query"
            attachments = None
            web_search = False
            web_search_provider = None

        response = await send_message_stream(conversation_id, MockRequest(), current_user="guest")
        async for _chunk in response.body_iterator:
            pass

    assert seen_kwargs.get("system_prompt") == "Answer like a pirate"


# ---------------------------------------------------------------------------
# Conversation-history windowing (was unbounded)
# ---------------------------------------------------------------------------

def _exchange(i, answer_size=20):
    return [
        {"role": "user", "content": f"question {i}"},
        {"role": "assistant", "stage3": {"response": f"answer {i} " + "x" * answer_size}},
    ]


def test_short_history_is_included_verbatim_without_marker():
    from ..council import build_context_prompt

    history = _exchange(1) + _exchange(2)
    prompt = build_context_prompt(history, "follow-up")

    assert "question 1" in prompt
    assert "question 2" in prompt
    assert "[earlier context omitted]" not in prompt


def test_long_history_is_windowed_to_recent_messages():
    from ..council import build_context_prompt, MAX_CONTEXT_MESSAGES

    history = []
    for i in range(20):  # 40 messages, far beyond the window
        history.extend(_exchange(i))
    prompt = build_context_prompt(history, "follow-up")

    assert "[earlier context omitted]" in prompt
    assert "question 19" in prompt  # most recent survives
    assert "question 0" not in prompt  # oldest dropped
    # No more than the window's worth of exchanges present
    assert prompt.count("question ") <= MAX_CONTEXT_MESSAGES


def test_char_budget_drops_oldest_parts_first():
    from ..council import build_context_prompt, MAX_CONTEXT_CHARS

    # Two exchanges with ~15k-char answers -> exceeds the 24k budget
    history = _exchange(1, answer_size=15_000) + _exchange(2, answer_size=15_000)
    prompt = build_context_prompt(history, "follow-up")

    assert "[earlier context omitted]" in prompt
    assert "answer 2" in prompt  # newest kept
    # The history block respects the budget (allow formatting overhead)
    assert len(prompt) < MAX_CONTEXT_CHARS + 1_000


def test_single_oversized_message_is_truncated():
    from ..council import build_context_prompt, MAX_CONTEXT_CHARS

    history = [{"role": "user", "content": "y" * (MAX_CONTEXT_CHARS * 2)}]
    prompt = build_context_prompt(history, "follow-up")

    assert "[earlier context omitted]" in prompt
    assert len(prompt) < MAX_CONTEXT_CHARS + 1_000


def test_empty_history_returns_query_unchanged():
    from ..council import build_context_prompt

    assert build_context_prompt([], "just the query") == "just the query"
