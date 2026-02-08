"""Tests for per-conversation router_type persistence and inference."""

import json


def test_create_conversation_persists_router_type_in_json_storage(tmp_path, monkeypatch):
    """
    router_type is a conversation-level setting, so it must be persisted in storage.
    """
    from .. import storage

    monkeypatch.setattr(storage.config, "DATA_DIR", str(tmp_path))

    conversation_id = "00000000-0000-0000-0000-000000000110"
    created = storage.create_conversation(
        conversation_id,
        models=["llama3.1:latest"],
        chairman="llama3.1:latest",
        username="u",
        execution_mode="full",
        router_type="ollama",
    )

    assert created["router_type"] == "ollama"

    loaded = storage.get_conversation(conversation_id)
    assert loaded is not None
    assert loaded["router_type"] == "ollama"


def test_missing_router_type_is_inferred_from_models(tmp_path, monkeypatch):
    """
    Old conversations won't have router_type; infer it from model id patterns.

    Heuristic:
    - any model id containing '/' => openrouter
    - otherwise => ollama
    """
    from .. import storage

    monkeypatch.setattr(storage.config, "DATA_DIR", str(tmp_path))

    conversation_id = "00000000-0000-0000-0000-000000000111"
    path = storage.get_conversation_path(conversation_id)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "id": conversation_id,
                "created_at": "now",
                "title": "t",
                "messages": [],
                "models": ["openai/gpt-5.1", "google/gemini-3-pro-preview"],
                "chairman": "google/gemini-3-pro-preview",
                "username": "u",
                # router_type intentionally omitted
            },
            f,
            indent=2,
        )

    loaded = storage.get_conversation(conversation_id)
    assert loaded is not None
    assert loaded["router_type"] == "openrouter"
