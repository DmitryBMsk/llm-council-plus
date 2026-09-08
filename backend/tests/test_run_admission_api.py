"""HTTP admission must reject before persistence/provider work and replay results."""

from unittest.mock import AsyncMock
import uuid

import pytest
from fastapi.testclient import TestClient
from backend import config, storage
from backend.main import app
from backend.api.routes import conversations


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "conversations"))
    monkeypatch.setattr(config, "MAX_COUNCIL_MODELS", 5)
    monkeypatch.setattr(storage, "is_using_database", lambda: False)
    monkeypatch.setenv("RUN_CONTROL_DB", str(tmp_path / "runs.db"))
    monkeypatch.setattr(conversations, "generate_conversation_title", AsyncMock(return_value="Run test"))
    return TestClient(app)


def test_model_limit_and_duplicates_enforced_at_api(client):
    assert client.post("/api/conversations", json={"models": [f"m{i}" for i in range(6)]}).status_code == 422
    assert client.post("/api/conversations", json={"models": ["m", "m"]}).status_code == 422


def test_same_request_id_replays_without_duplicate_message(client, monkeypatch):
    run = AsyncMock(return_value=([{"model": "m", "response": "answer"}], None, None, {}))
    monkeypatch.setattr(conversations, "run_full_council", run)
    cid = client.post("/api/conversations", json={"models": ["m"], "execution_mode": "chat_only"}).json()["id"]
    body = {"content": "same", "request_id": str(uuid.uuid4())}
    one = client.post(f"/api/conversations/{cid}/message", json=body)
    two = client.post(f"/api/conversations/{cid}/message", json=body)
    assert one.status_code == two.status_code == 200
    assert one.json() == two.json()
    assert run.await_count == 1
    assert len(client.get(f"/api/conversations/{cid}").json()["messages"]) == 2
    bad = client.post(f"/api/conversations/{cid}/message", json={**body, "content": "different"})
    assert bad.status_code == 409


def test_rate_limit_rejects_before_saving_user_message(client, monkeypatch):
    monkeypatch.setenv("RUN_RATE_REQUESTS", "1")
    run = AsyncMock(return_value=([{"model": "m", "response": "answer"}], None, None, {}))
    monkeypatch.setattr(conversations, "run_full_council", run)
    cid = client.post("/api/conversations", json={"models": ["m"]}).json()["id"]
    assert client.post(f"/api/conversations/{cid}/message", json={"content": "first"}).status_code == 200
    limited = client.post(f"/api/conversations/{cid}/message", json={"content": "second"})
    assert limited.status_code == 429
    assert "retry-after" in limited.headers
    assert run.await_count == 1
    assert len(client.get(f"/api/conversations/{cid}").json()["messages"]) == 2
