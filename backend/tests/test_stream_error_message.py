"""An unexpected failure in /message/stream reaches the browser as a fixed message, never as exception text."""

import json
import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend import config, router_dispatch, storage
from backend.main import app


@pytest.fixture
def cid(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "conversations"))
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(config, "ENABLE_MEMORY", False)
    monkeypatch.setattr(storage, "is_using_database", lambda: False)

    async def streaming(router_type, models, messages, **kwargs):
        for model in models:
            yield model, {"content": "ANSWER", "finish_reason": "stop", "truncated": False}

    async def single(router_type, *, model, messages, **kwargs):
        return {"content": "A title", "finish_reason": "stop", "truncated": False}

    monkeypatch.setattr(router_dispatch, "query_models_streaming", streaming)
    monkeypatch.setattr(router_dispatch, "query_model", single)
    conversation_id = str(uuid4())
    storage.create_conversation(conversation_id, models=["a/alpha"], router_type="openrouter", execution_mode="chat_only")
    return conversation_id


def test_database_error_text_stays_in_the_server_log(cid, monkeypatch, caplog):
    def failed_write(*args, **kwargs):
        raise OperationalError(
            "UPDATE conversations SET messages=?",
            ('[{"metadata": {"stage1_prompt": {"text": "PRIVATE_PROMPT_88"}}}]',),
            Exception("database is locked"),
        )

    monkeypatch.setattr(storage, "add_assistant_message", failed_write)
    body = {"content": "Explain the topic", "request_id": str(uuid4())}

    with caplog.at_level(logging.ERROR):
        response = TestClient(app).post(f"/api/conversations/{cid}/message/stream", json=body)

    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    errors = [event["message"] for event in events if event["type"] == "error"]
    assert errors == ["The council run failed. Please try again."]
    assert "PRIVATE_PROMPT_88" not in response.text
    assert "UPDATE conversations" not in response.text
    assert "PRIVATE_PROMPT_88" in caplog.text
