"""A reloaded conversation carries the provider usage summary its run reported (#56)."""

import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from backend import config, storage, usage
from backend.api.routes import conversations as routes
from backend.main import app

STAGE_USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.01}
TITLE_USAGE = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}  # no cost reported


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "is_using_database", lambda: False)
    monkeypatch.setattr(storage.config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(routes, "_models_cache", {})
    return TestClient(app)


def new_conversation(client):
    created = client.post(
        "/api/conversations",
        json={"models": ["model-a"], "execution_mode": "chat_only", "router_type": "openrouter"},
    )
    assert created.status_code == 200
    return created.json()["id"]


def saved_usage(client, conversation_id):
    messages = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
    return messages[-1]["metadata"]["provider_usage"]


def test_message_route_saves_the_usage_summary_it_returns(client, monkeypatch):
    async def fake_title(_query, router_type=None):
        usage.record_usage("openrouter", "title-model", TITLE_USAGE, stage="TITLE")
        return "Title"

    async def fake_council(_query, _history=None, **_kwargs):
        usage.record_usage("openrouter", "model-a", STAGE_USAGE, stage="STAGE1")
        return [{"model": "model-a", "response": "answer", "usage": STAGE_USAGE}], None, None, {
            "execution_mode": "chat_only"}

    monkeypatch.setattr(routes, "generate_conversation_title", fake_title)
    monkeypatch.setattr(routes, "run_full_council", fake_council)
    conversation_id = new_conversation(client)

    response = client.post(f"/api/conversations/{conversation_id}/message", json={"content": "Question"})

    assert response.status_code == 200
    saved = saved_usage(client, conversation_id)
    assert saved == response.json()["metadata"]["provider_usage"]
    assert saved["attempts"] == 2
    assert saved["totals"] == {"prompt_tokens": 13, "completion_tokens": 7, "total_tokens": 20,
                               "provider_cost": 0.01}
    assert saved["coverage"]["provider_cost"] == 1
    assert saved["complete"] is False


def stream_usage(client, conversation_id, body):
    """Send one streamed message and return the usage summary of its complete event."""
    response = client.post(f"/api/conversations/{conversation_id}/message/stream", json=body)
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    return next(event for event in events if event["type"] == "complete")["metadata"]["provider_usage"]


def test_stream_route_saves_the_summary_of_the_complete_event(client, monkeypatch):
    """The title call ends after the message is saved; its usage must still be stored."""
    message_saved = []
    saved_before_title_ended = []
    late_writes = []
    real_save = storage.add_assistant_message
    real_late_write = storage.update_last_assistant_metadata

    def save(*args, **kwargs):
        real_save(*args, **kwargs)
        message_saved.append(True)

    def late_write(*args, **kwargs):
        late_writes.append(args)
        real_late_write(*args, **kwargs)

    async def fake_title(_query, router_type=None):
        for _ in range(200):  # bounded: a route that awaits the title first must fail, not hang
            if message_saved:
                break
            await asyncio.sleep(0.01)
        saved_before_title_ended.append(bool(message_saved))
        usage.record_usage("openrouter", "title-model", TITLE_USAGE, stage="TITLE")
        return "Title"

    async def fake_stage1(*_args, **_kwargs):
        usage.record_usage("openrouter", "model-a", STAGE_USAGE, stage="STAGE1")
        yield {"model": "model-a", "response": "answer", "usage": STAGE_USAGE}

    monkeypatch.setattr(storage, "add_assistant_message", save)
    monkeypatch.setattr(storage, "update_last_assistant_metadata", late_write)
    monkeypatch.setattr(routes, "generate_conversation_title", fake_title)
    monkeypatch.setattr(routes, "stage1_collect_responses_streaming", fake_stage1)
    conversation_id = new_conversation(client)

    first = {"content": "Question", "request_id": str(uuid.uuid4())}
    sent = stream_usage(client, conversation_id, first)

    assert saved_before_title_ended == [True], "the assistant message was not saved while the title call ran"
    assert sent["attempts"] == 2
    assert sent["totals"]["prompt_tokens"] == 13
    assert saved_usage(client, conversation_id) == sent
    assert len(late_writes) == 1

    # A retry with the same request ID replays the cached run with its summary
    assert stream_usage(client, conversation_id, first) == sent

    # A follow-up has no title call: its summary is final at the save, with no second write
    follow_up = stream_usage(client, conversation_id, {"content": "More"})
    assert follow_up["attempts"] == 1
    assert saved_usage(client, conversation_id) == follow_up
    assert len(late_writes) == 1
