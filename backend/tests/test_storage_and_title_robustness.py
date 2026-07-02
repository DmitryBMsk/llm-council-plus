"""Regression tests for storage robustness and title generation.

Covers three quick-win fixes:
- a torn/corrupt conversation file must not raise (500) — it is treated as missing;
- a serialization failure during read-modify-write must not destroy the on-disk file;
- generate_conversation_title must survive a model response with content=None.
"""

from __future__ import annotations

import json

import pytest


def _isolate_json_storage(storage, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "is_using_database", lambda: False)
    monkeypatch.setattr(storage.config, "DATA_DIR", str(tmp_path))


def test_get_conversation_returns_none_on_corrupt_json(tmp_path, monkeypatch):
    from .. import storage

    _isolate_json_storage(storage, tmp_path, monkeypatch)

    conversation_id = "00000000-0000-0000-0000-000000002001"
    path = tmp_path / f"{conversation_id}.json"
    path.write_text('{"id": "torn file, no closing brace')

    assert storage.get_conversation(conversation_id) is None


def test_update_conversation_preserves_file_when_serialization_fails(tmp_path, monkeypatch):
    from .. import storage

    _isolate_json_storage(storage, tmp_path, monkeypatch)

    conversation_id = "00000000-0000-0000-0000-000000002002"
    storage.create_conversation(conversation_id, models=None, chairman=None, username=None)
    storage.add_user_message(conversation_id, "must survive")

    def poison(conversation):
        conversation["bad"] = object()  # not JSON-serializable

    with pytest.raises(TypeError):
        storage._json_update_conversation(conversation_id, poison)

    # The pre-image must still be intact and loadable.
    path = tmp_path / f"{conversation_id}.json"
    loaded = json.loads(path.read_text())
    assert [m["content"] for m in loaded["messages"] if m["role"] == "user"] == ["must survive"]


@pytest.mark.asyncio
async def test_generate_conversation_title_handles_null_content(monkeypatch):
    from .. import council

    async def fake_query_model(router_type, model, messages, timeout, stage):
        return {"content": None, "reasoning_details": None}

    monkeypatch.setattr(council.router_dispatch, "query_model", fake_query_model)

    title = await council.generate_conversation_title("What is the meaning of life?")
    assert title == "New Conversation"
