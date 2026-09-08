"""Run caches must respect temporary/deleted data and retain failure accounting."""
import asyncio
import json
import sqlite3
from unittest.mock import AsyncMock
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
import pytest

from backend import config, storage, usage
from backend.api.deps import get_current_user
from backend.api.routes import conversations
from backend.run_routes import managed_run


@pytest.fixture
def run_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "conversations"))
    monkeypatch.setattr(config, "COUNCIL_MODELS", ["m"])
    monkeypatch.setattr(config, "MAX_COUNCIL_MODELS", 5)
    monkeypatch.setattr(config, "ROUTER_TYPE", "ollama")
    monkeypatch.setattr(storage, "is_using_database", lambda: False)
    monkeypatch.setenv("RUN_CONTROL_DB", str(tmp_path / "runs.db"))
    monkeypatch.setattr(conversations, "generate_conversation_title", AsyncMock(return_value="Test title"))
    app = FastAPI()
    app.include_router(conversations.router)

    async def identity(request: Request):
        return request.headers.get("X-Test-User", "guest")

    app.dependency_overrides[get_current_user] = identity
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, tmp_path / "runs.db"


def records(db_path):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM runs")]


def test_temporary_reply_never_persists_body_or_reexecutes_same_id(run_client, monkeypatch):
    client, db_path = run_client
    marker = "PRIVATE_TEMPORARY_REPLY"
    provider = AsyncMock(return_value=([{"model": "m", "response": marker}], None, None, {}))
    monkeypatch.setattr(conversations, "run_full_council", provider)
    body = {"content": "Private temporary question", "temporary": True, "request_id": str(uuid.uuid4())}
    cid = str(uuid.uuid4())
    first = client.post(f"/api/conversations/{cid}/message", json=body)
    assert first.status_code == 200, first.text
    assert marker in first.text
    assert marker not in json.dumps(records(db_path))
    assert client.get("/api/conversations").json() == []
    retry = client.post(f"/api/conversations/{cid}/message", json=body)
    assert retry.status_code == 409, retry.text
    assert provider.await_count == 1


@pytest.mark.parametrize("delete_all", [False, True])
def test_deletion_scrubs_cached_run_body_but_does_not_replay(run_client, monkeypatch, delete_all):
    client, db_path = run_client
    marker = "PRIVATE_DELETED_REPLY"
    provider = AsyncMock(return_value=([{"model": "m", "response": marker}], None, None, {}))
    monkeypatch.setattr(conversations, "run_full_council", provider)
    cid = client.post("/api/conversations", json={"models": ["m"], "router_type": "ollama"}).json()["id"]
    body = {"content": "Private question", "request_id": str(uuid.uuid4())}
    first = client.post(f"/api/conversations/{cid}/message", json=body)
    assert first.status_code == 200, first.text
    assert marker in json.dumps(records(db_path))
    deletion = client.delete("/api/conversations" if delete_all else f"/api/conversations/{cid}")
    assert deletion.is_success, deletion.text
    assert marker not in json.dumps(records(db_path))
    assert client.post(f"/api/conversations/{cid}/message", json=body).status_code == 404
    assert provider.await_count == 1


def test_failed_run_retains_observed_paid_usage(run_client, monkeypatch):
    client, db_path = run_client
    async def fail_after_paid_call(*args, **kwargs):
        usage.record_usage("openrouter", "paid-model", {"total_tokens": 7, "cost": 0.1}, stage="STAGE1")
        raise RuntimeError("Failure after paid provider response")
    monkeypatch.setattr(conversations, "run_full_council", fail_after_paid_call)
    cid = client.post("/api/conversations", json={"models": ["m"], "router_type": "ollama"}).json()["id"]
    result = client.post(f"/api/conversations/{cid}/message", json={"content": "hello"})
    assert result.status_code == 500
    row = records(db_path)[0]
    assert row["status"] in {"failed", "aborted"}
    assert row["usage"] is not None
    ledger = json.loads(row["usage"])
    assert ledger["totals"]["total_tokens"] == 7
    assert ledger["totals"]["provider_cost"] == 0.1


@pytest.mark.asyncio
async def test_temporary_request_cannot_reserve_another_users_conversation(run_client, monkeypatch):
    _, _db_path = run_client
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    cid = str(uuid.uuid4())
    storage.create_conversation(cid, models=["m"], username="alice", router_type="ollama")
    started, release = asyncio.Event(), asyncio.Event()

    @managed_run()
    async def normal(conversation_id, request, current_user):
        return {"stage1": [{"response": "Alice answer"}]}

    @managed_run()
    async def temporary(conversation_id, request, current_user):
        started.set()
        await release.wait()
        return {"stage1": [{"response": "Bob temporary"}]}

    bob = asyncio.create_task(temporary(cid, conversations.SendMessageRequest(content="hello", temporary=True), current_user="bob"))
    try:
        # A fix may reject Bob up front or isolate his temporary reservation.
        waiter = asyncio.create_task(started.wait())
        done, _ = await asyncio.wait([waiter, bob], return_when=asyncio.FIRST_COMPLETED, timeout=5)
        assert done
        if bob in done:
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as error:
                await bob
            assert error.value.status_code in {403, 404}
        result = await normal(cid, conversations.SendMessageRequest(content="hello"), current_user="alice")
        assert result["stage1"][0]["response"] == "Alice answer"
    finally:
        release.set()
        await asyncio.gather(bob, return_exceptions=True)
        if 'waiter' in locals() and not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
async def test_asgi_disconnect_closes_stream_before_finalizing_ticket(run_client, spec_version):
    _, db_path = run_client
    cid = str(uuid.uuid4())
    storage.create_conversation(cid, models=["m"])
    cleaned = []

    @managed_run(streaming=True)
    async def streaming(conversation_id, request, current_user):
        async def events():
            try:
                usage.record_usage("openrouter", "m", {"total_tokens": 5, "cost": 0.02})
                yield "data: " + json.dumps({"type": "stage1_model_response", "data": {"model": "m", "response": "PARTIAL"}}) + "\n\n"
                await asyncio.Event().wait()
            finally:
                cleaned.append(True)
        return StreamingResponse(events(), media_type="text/event-stream")

    response = await streaming(cid, conversations.SendMessageRequest(content="hello"), current_user="guest")
    disconnected = asyncio.Event()
    async def receive():
        await disconnected.wait()
        return {"type": "http.disconnect"}
    async def send(message):
        if message["type"] == "http.response.body":
            if spec_version == "2.4":
                raise OSError("Client socket closed")
            disconnected.set()
            await asyncio.Event().wait()
    try:
        scope = {"type": "http", "asgi": {"spec_version": spec_version}}
        if spec_version == "2.4":
            from starlette.requests import ClientDisconnect
            with pytest.raises(ClientDisconnect):
                await response(scope, receive, send)
        else:
            await response(scope, receive, send)
        assert cleaned, "Disconnect returned without closing the provider/stage generator"
        row = records(db_path)[0]
        assert row["status"] == "partial"
        assert json.loads(row["result"])["stage1"][0]["response"] == "PARTIAL"
        assert json.loads(row["usage"])["totals"]["total_tokens"] == 5
    finally:
        # Cleanup for the failing implementation; the fixed response closes itself.
        try:
            await response.body_iterator.aclose()
        except ValueError:
            pass


@pytest.mark.asyncio
async def test_run_admitted_during_deletion_cannot_recache_private_reply(run_client, monkeypatch):
    _, db_path = run_client
    import threading

    cid = str(uuid.uuid4())
    storage.create_conversation(cid, models=["m"], execution_mode="chat_only", router_type="ollama")
    deleting, allow_delete = threading.Event(), threading.Event()
    provider_started, release_provider = asyncio.Event(), asyncio.Event()
    original_delete = storage._json_delete_conversation

    def paused_delete(conversation_id):
        deleting.set()
        assert allow_delete.wait(5)
        return original_delete(conversation_id)

    async def provider(*args, **kwargs):
        provider_started.set()
        await release_provider.wait()
        yield {"model": "m", "response": "PRIVATE_FINISHED_AFTER_DELETE"}

    monkeypatch.setattr(storage, "_json_delete_conversation", paused_delete)
    monkeypatch.setattr(conversations, "stage1_collect_responses_streaming", provider)
    deletion = asyncio.create_task(asyncio.to_thread(storage.delete_conversation, cid))
    execution = None
    try:
        assert await asyncio.to_thread(deleting.wait, 5)
        response = await conversations.send_message_stream(
            cid, conversations.SendMessageRequest(content="hello"), current_user="guest")
        async def consume():
            return [chunk async for chunk in response.body_iterator]
        execution = asyncio.create_task(consume())
        await asyncio.wait_for(provider_started.wait(), timeout=5)
        allow_delete.set()
        assert await deletion
        release_provider.set()
        await asyncio.gather(execution, return_exceptions=True)
        assert storage.get_conversation(cid) is None
        assert "PRIVATE_FINISHED_AFTER_DELETE" not in json.dumps(records(db_path))
    finally:
        allow_delete.set()
        release_provider.set()
        await asyncio.gather(deletion, return_exceptions=True)
        if execution is not None:
            await asyncio.gather(execution, return_exceptions=True)


@pytest.mark.asyncio
async def test_disconnect_before_stream_iteration_releases_lease(run_client):
    _, db_path = run_client
    from starlette.requests import ClientDisconnect

    cid = str(uuid.uuid4())
    storage.create_conversation(cid, models=["m"])
    started = []

    @managed_run(streaming=True)
    async def streaming(conversation_id, request, current_user):
        async def events():
            started.append(True)
            yield 'data: {"type":"complete"}\n\n'
        return StreamingResponse(events(), media_type="text/event-stream")

    response = await streaming(cid, conversations.SendMessageRequest(content="hello"), current_user="guest")
    async def receive():
        await asyncio.Event().wait()
    async def send(message):
        assert message["type"] == "http.response.start"
        raise OSError("Socket already closed before response headers")
    try:
        with pytest.raises(ClientDisconnect):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        assert not started
        assert records(db_path)[0]["status"] == "aborted"
    finally:
        # Never leave a heartbeat thread from the failing implementation behind.
        if response.background:
            await response.background()
