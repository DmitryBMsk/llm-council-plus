"""Unexpected failures reach the browser as fixed messages; exception text stays in the server log."""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend import config, ollama, openrouter, router_dispatch, storage, tools
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
    logged = [r for r in caplog.records if "Exception during streaming" in r.getMessage()]
    assert len(logged) == 1 and isinstance(logged[0].exc_info[1], OperationalError)


@pytest.mark.parametrize("adapter", [openrouter, ollama])
def test_unexpected_provider_error_text_stays_in_the_server_log(adapter, monkeypatch, caplog):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-test-key", raising=False)
    client = AsyncMock()
    client.post.side_effect = RuntimeError("PROVIDER_INTERNALS_77")
    client.__aenter__.return_value = client
    monkeypatch.setattr(adapter.httpx, "AsyncClient", MagicMock(return_value=client))

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(adapter.query_model("a/alpha", [{"role": "user", "content": "hi"}]))

    assert result["error"] is True
    assert result["error_message"] == "Unexpected provider error"
    assert "PROVIDER_INTERNALS_77" in caplog.text


def test_exa_failure_text_is_not_returned_as_search_evidence(monkeypatch, caplog):
    class FailingExa:
        def __init__(self, api_key):
            pass

        def search_and_contents(self, *args, **kwargs):
            raise RuntimeError("EXA_INTERNALS_55")

    monkeypatch.setattr(tools, "Exa", FailingExa)

    with caplog.at_level(logging.ERROR):
        result = tools.exa_tool("exa-test-key").func("latest news")

    assert result == "Exa search error: search failed"
    assert "EXA_INTERNALS_55" in caplog.text


@pytest.mark.parametrize(
    "adapter,message",
    [
        (openrouter, "Network error while talking to OpenRouter API"),
        (ollama, "Network error while talking to Ollama at ollama.test:11434"),
    ],
)
def test_dropped_provider_connection_is_named_without_its_details(adapter, message, monkeypatch, caplog):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-test-key", raising=False)
    monkeypatch.setattr(config, "OLLAMA_HOST", "ollama.test:11434", raising=False)
    client = AsyncMock()
    client.post.side_effect = httpx.RemoteProtocolError("PEER_CLOSED_31")
    client.__aenter__.return_value = client
    monkeypatch.setattr(adapter.httpx, "AsyncClient", MagicMock(return_value=client))

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(adapter.query_model("a/alpha", [{"role": "user", "content": "hi"}]))

    assert (result["error_type"], result["error_message"]) == ("connection", message)
    assert "PEER_CLOSED_31" in caplog.text


@pytest.mark.parametrize("adapter", [openrouter, ollama])
def test_provider_timeout_keeps_its_own_message(adapter, monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "sk-test-key", raising=False)
    client = AsyncMock()
    client.post.side_effect = httpx.ReadTimeout("SLOW_PROVIDER")  # a TransportError subclass too
    client.__aenter__.return_value = client
    monkeypatch.setattr(adapter.httpx, "AsyncClient", MagicMock(return_value=client))

    result = asyncio.run(adapter.query_model("a/alpha", [{"role": "user", "content": "hi"}]))

    assert result["error_type"] == "timeout"
    assert result["error_message"].startswith("Request timed out after")
