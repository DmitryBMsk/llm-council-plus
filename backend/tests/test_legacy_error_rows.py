"""Error rows stored before #67 and #73 come back without exception text or proxy credentials (#74)."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import config, router_dispatch, runtime_settings, storage
from backend.api.routes import conversations
from backend.main import app

# (error_type, message as stored before #67/#73, message shown now)
ROWS = [
    ("unknown", "RuntimeError: SDK_INTERNALS_74 calling https://api.example/v1", "Unexpected provider error"),
    ("connection", "Cannot connect to Ollama at user:PROXY_SECRET@ollama.test:11434. Is Ollama running?",
     "Cannot connect to Ollama at ollama.test:11434. Is Ollama running?"),
    ("connection", "Cannot connect to Ollama at user:PROXY_SECRET@127.0.0.1:11434/proxy@v2. Is Ollama running?",
     "Cannot connect to Ollama at 127.0.0.1:11434. Is Ollama running?"),
    ("connection", "Cannot connect to Ollama at user:PROXY_SECRET@ollama.test:port. Is Ollama running?",
     "Cannot connect to Ollama. Is Ollama running?"),
    # An unescaped '/' in the password: httpx reads 'PROXY_USER:4321' as the host and port
    ("connection", "Cannot connect to Ollama at PROXY_USER:4321/PROXY_SECRET@ollama.test:11434. Is Ollama running?",
     "Cannot connect to Ollama. Is Ollama running?"),
    ("connection", "Cannot connect to Ollama at [fe80::1%é]:11434. Is Ollama running?",
     "Cannot connect to Ollama. Is Ollama running?"),
    ("timeout", "Request timed out after 120s", "Request timed out after 120s"),
    ("connection", "Cannot connect to OpenRouter API", "Cannot connect to OpenRouter API"),
    ("unknown", "No response received", "No response received"),
]
MODELS = ["ok"] + [f"m{i}" for i in range(len(ROWS))]
SHOWN = {f"m{i}": shown for i, (_, _, shown) in enumerate(ROWS)}
LEAKS = ("SDK_INTERNALS_74", "PROXY_SECRET", "PROXY_USER")


def stored_rows():
    return [{"model": "ok", "response": "answer"}] + [
        {"model": f"m{i}", "error": True, "error_type": kind, "error_message": stored}
        for i, (kind, stored, _) in enumerate(ROWS)
    ]


def shown(rows):
    return {row["model"]: row["error_message"] for row in rows if row.get("error")}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(config, "ENABLE_MEMORY", False)
    monkeypatch.setattr(config, "MAX_COUNCIL_MODELS", len(MODELS))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "conversations"))
    monkeypatch.setattr(storage, "is_using_database", lambda: False)
    monkeypatch.setattr(conversations, "generate_conversation_title", AsyncMock(return_value="Legacy"))
    return TestClient(app)


def conversation(client):
    return client.post("/api/conversations", json={"models": MODELS, "execution_mode": "chat_only"}).json()["id"]


def test_non_stream_run_comes_back_clean_from_get_and_replay(client, monkeypatch):
    stage2 = [{"model": "m0", "error": True, "error_type": "unknown", "error_message": "SDK_INTERNALS_74"}]
    monkeypatch.setattr(conversations, "run_full_council", AsyncMock(return_value=(stored_rows(), stage2, None, {})))
    cid = conversation(client)
    body = {"content": "hi", "request_id": str(uuid4())}
    client.post(f"/api/conversations/{cid}/message", json=body)

    replay = client.post(f"/api/conversations/{cid}/message", json=body)
    saved = client.get(f"/api/conversations/{cid}")

    for response, record in ((replay, replay.json()), (saved, saved.json()["messages"][-1])):
        assert shown(record["stage1"]) == SHOWN
        assert shown(record["stage2"]) == {"m0": "Unexpected provider error"}
        assert not any(leak in response.text for leak in LEAKS)


def test_streamed_run_comes_back_clean_from_get_and_replay(client, monkeypatch):
    rows = {row["model"]: row for row in stored_rows()}

    async def streaming(router_type, models, messages, **kwargs):
        for model in models:
            row = rows[model]
            yield model, {"content": row["response"]} if "response" in row else {
                key: row[key] for key in ("error", "error_type", "error_message")
            }

    monkeypatch.setattr(router_dispatch, "query_models_streaming", streaming)
    cid = conversation(client)
    body = {"content": "hi", "request_id": str(uuid4())}
    client.post(f"/api/conversations/{cid}/message/stream", json=body)

    replay = client.post(f"/api/conversations/{cid}/message/stream", json=body)
    saved = client.get(f"/api/conversations/{cid}")

    events = [json.loads(line[6:]) for line in replay.text.splitlines() if line.startswith("data: ")]
    replayed = next(event["data"] for event in events if event["type"] == "stage1_complete")
    assert shown(replayed) == shown(saved.json()["messages"][-1]["stage1"]) == SHOWN
    assert not any(leak in replay.text + saved.text for leak in LEAKS)
