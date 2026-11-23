"""The Stage 1 prompt of a council run is kept server-side so /retry-model can replay it."""

import asyncio
import base64
import copy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import config, council, router_dispatch, run_routes, runtime_settings, storage
from backend.main import app
from backend.runtime_settings import RuntimeSettings

ALPHA, BETA = "a/alpha", "b/beta"
ENDPOINTS = ["message", "message/stream"]
ANSWERS = {
    ALPHA: {"error": True, "error_type": "timeout", "error_message": "Request timed out"},
    BETA: {"content": "BETA_ANSWER", "finish_reason": "stop", "truncated": False},
}


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "conversations"))
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(config, "ENABLE_MEMORY", False)
    monkeypatch.setattr(storage, "is_using_database", lambda: False)
    state = SimpleNamespace(
        template="ORIGINAL TEMPLATE\n{full_query}", memory="MEMORY_NOTE_19", memory_reads=0, sent=[], retried=[]
    )
    monkeypatch.setattr(
        runtime_settings, "get_runtime_settings", lambda: RuntimeSettings(stage1_prompt_template=state.template)
    )

    class Memory:
        def __init__(self, conversation_id):
            pass

        def get_context(self, query):
            state.memory_reads += 1
            return state.memory

        def save_exchange(self, query, response):
            pass

    monkeypatch.setattr(council, "CouncilMemorySystem", Memory)

    async def parallel(router_type, models, messages, **kwargs):
        state.sent.append(copy.deepcopy(messages))
        return {model: ANSWERS[model] for model in models}

    async def streaming(router_type, models, messages, **kwargs):
        state.sent.append(copy.deepcopy(messages))
        for model in models:
            yield model, ANSWERS[model]

    async def single(router_type, *, model, messages, **kwargs):
        if kwargs.get("stage") == "STAGE1":
            state.retried.append(copy.deepcopy(messages))
        return {"content": "Fresh answer", "finish_reason": "stop", "truncated": False}

    monkeypatch.setattr(router_dispatch, "query_models_parallel", parallel)
    monkeypatch.setattr(router_dispatch, "query_models_streaming", streaming)
    monkeypatch.setattr(router_dispatch, "query_model", single)
    state.client = TestClient(app)
    state.cid = new_conversation("chat_only")
    return state


def new_conversation(execution_mode):
    cid = str(uuid4())
    storage.create_conversation(
        cid,
        models=[ALPHA, BETA],
        router_type="openrouter",
        system_prompt="Original policy",
        execution_mode=execution_mode,
    )
    return cid


def send(run, endpoint, **body):
    body = {"content": "Explain the topic", "request_id": str(uuid4()), **body}
    return run.client.post(f"/api/conversations/{run.cid}/{endpoint}", json=body)


def retry(run, message_index=1):
    body = {"message_index": message_index, "model": ALPHA, "request_id": str(uuid4())}
    return run.client.post(f"/api/conversations/{run.cid}/retry-model", json=body)


def stored_metadata(run, index=1):
    return storage.get_conversation(run.cid)["messages"][index]["metadata"]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_rendered_prompt_is_stored_but_never_sent_to_the_browser(run, endpoint):
    body = {"content": "Explain the topic", "request_id": str(uuid4())}

    response = run.client.post(f"/api/conversations/{run.cid}/{endpoint}", json=body)
    replay = run.client.post(f"/api/conversations/{run.cid}/{endpoint}", json=body)
    conversation = run.client.get(f"/api/conversations/{run.cid}")

    assert response.status_code == replay.status_code == conversation.status_code == 200
    assert len(run.sent) == 1
    assert stored_metadata(run)["stage1_prompt"] == {
        "text": "ORIGINAL TEMPLATE\nExplain the topic",
        "memory_context": None,
    }
    for text in (response.text, replay.text, conversation.text):
        assert "stage1_prompt" not in text
    assert conversation.json()["messages"][1]["metadata"]["execution_mode"] == "chat_only"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_retry_sends_the_original_prompt_after_the_template_and_memory_changed(run, monkeypatch, endpoint):
    monkeypatch.setattr(config, "ENABLE_MEMORY", True)
    monkeypatch.setattr(council, "requires_tools", lambda query: True)

    async def evidence(query, router_type=None):
        return [{"tool": "search", "result": "STORED_EVIDENCE_55"}]

    monkeypatch.setattr(council, "collect_auto_tools", evidence)
    assert send(run, endpoint).status_code == 200
    run.template = "CHANGED TEMPLATE {full_query}"
    run.memory = "NEWER_MEMORY_NOTE"
    reads = run.memory_reads

    response = retry(run)

    assert response.status_code == 200, response.text
    assert run.retried == run.sent
    assert [m["role"] for m in run.retried[0]] == ["system", "system", "system", "user"]
    assert run.retried[0][1] == {"role": "system", "content": "Relevant past exchanges:\nMEMORY_NOTE_19"}
    assert "STORED_EVIDENCE_55" in run.retried[0][2]["content"]
    assert run.memory_reads == reads


def test_message_saved_before_the_change_is_retried_with_the_current_template(run, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_MEMORY", True)
    storage.add_user_message(run.cid, "Explain the topic")
    storage.add_assistant_message(run.cid, [{"model": ALPHA, **ANSWERS[ALPHA]}], None, None, {"tool_outputs": []})
    run.template = "CURRENT TEMPLATE {full_query}"

    response = retry(run)

    assert response.status_code == 200, response.text
    assert run.retried[0] == [
        {"role": "system", "content": "Original policy"},
        {"role": "user", "content": "CURRENT TEMPLATE Explain the topic"},
    ]
    assert run.memory_reads == 0


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_prompt_of_an_oversized_question_is_not_stored(run, endpoint):
    document = {"filename": "big.txt", "file_type": "txt", "content": "x" * 500_001}

    response = send(run, endpoint, attachments=[document])

    assert response.status_code == 200, response.text
    assert len(run.sent) == 1
    assert "stage1_prompt" not in stored_metadata(run)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_prompt_rendered_past_the_limit_is_not_stored(run, endpoint):
    run.template = "{full_query}\n{full_query}"
    document = {"filename": "half.txt", "file_type": "txt", "content": "x" * 300_000}

    response = send(run, endpoint, attachments=[document])

    assert response.status_code == 200, response.text
    assert len(run.sent) == 1
    assert "stage1_prompt" not in stored_metadata(run)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_stored_prompt_holds_no_image_data(run, endpoint):
    data = "data:image/png;base64," + base64.b64encode(b"IMAGE_BYTES_42").decode()
    image = {"filename": "photo.png", "file_type": "image", "content": data}

    response = send(run, endpoint, attachments=[image])

    assert response.status_code == 200, response.text
    assert data in str(run.sent)
    assert stored_metadata(run)["stage1_prompt"]["text"] == "ORIGINAL TEMPLATE\nExplain the topic"


def test_interrupted_stream_keeps_the_prompt_with_its_partial_answers(run, monkeypatch):
    async def stage2_fails(*args, **kwargs):
        raise RuntimeError("ranking provider down")

    monkeypatch.setattr("backend.api.routes.conversations.stage2_collect_rankings", stage2_fails)
    run.cid = new_conversation("full")

    response = send(run, "message/stream")

    assert response.status_code == 200
    metadata = stored_metadata(run)
    assert metadata["partial"] is True
    assert metadata["stage1_prompt"]["text"] == "ORIGINAL TEMPLATE\nExplain the topic"


def stream_until_disconnect(run, body, event=None, nth=1, stall=False, gone=None):
    """POST /message/stream over raw ASGI and disconnect once the nth `event` is sent.

    stall=True keeps that send blocked, as on a stalled socket, so the disconnect lands mid-send.
    A caller that passes its own `gone` event may also set it to disconnect.
    """
    raw = json.dumps(body).encode()
    path = f"/api/conversations/{run.cid}/message/stream"
    # ASGI before 2.4: Starlette cancels the response task when the client disconnects
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(raw)).encode()),
        ],
    }

    gone = gone or asyncio.Event()

    async def disconnect():
        request = [{"type": "http.request", "body": raw, "more_body": False}]
        seen = 0

        async def receive():
            if request:
                return request.pop()
            await gone.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            nonlocal seen
            if event and f'"type": "{event}"'.encode() in message.get("body", b""):
                seen += 1
                if seen == nth:
                    gone.set()
                    if stall:
                        await asyncio.Event().wait()

        await asyncio.wait_for(app(scope, receive, send), timeout=10)

    asyncio.run(disconnect())


def test_client_disconnect_during_stage2_keeps_the_prompt_with_its_partial_answers(run, monkeypatch):
    async def stage2_hangs(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr("backend.api.routes.conversations.stage2_collect_rankings", stage2_hangs)
    run.cid = new_conversation("full")

    stream_until_disconnect(run, {"content": "Explain the topic", "request_id": str(uuid4())}, "stage2_start")

    metadata = stored_metadata(run)
    assert metadata["partial"] is True
    assert metadata["stage1_prompt"]["text"] == "ORIGINAL TEMPLATE\nExplain the topic"


@pytest.mark.parametrize("sent", [1, 2])
def test_stage1_answer_being_sent_on_disconnect_is_saved_like_its_replay(run, sent):
    body = {"content": "Explain the topic", "request_id": str(uuid4())}

    stream_until_disconnect(run, body, "stage1_model_response", nth=sent, stall=True)
    replay = run.client.post(f"/api/conversations/{run.cid}/message/stream", json=body)

    saved = storage.get_conversation(run.cid)["messages"][1]
    assert [row["model"] for row in saved["stage1"]] == [ALPHA, BETA][:sent]
    assert saved["metadata"]["partial"] is True
    assert saved["metadata"]["stage1_prompt"]["text"] == "ORIGINAL TEMPLATE\nExplain the topic"
    events = [json.loads(line[6:]) for line in replay.text.splitlines() if line.startswith("data: ")]
    replayed = next(event["data"] for event in events if event["type"] == "stage1_complete")
    assert [row["model"] for row in replayed] == [ALPHA, BETA][:sent]


def test_answer_waiting_for_the_lease_check_on_disconnect_is_saved_like_its_replay(run, monkeypatch):
    gone, lease_checks = asyncio.Event(), []
    run_in_threadpool = run_routes.run_in_threadpool

    async def busy_thread_pool(func, *args, **kwargs):
        # Fault injection: no free thread for the lease check that holds the second answer
        if getattr(func, "__name__", None) == "ensure_active":
            lease_checks.append(func)
            if len(lease_checks) == 3:  # stage1_start and alpha went out; beta waits here
                gone.set()
                await asyncio.Event().wait()
        return await run_in_threadpool(func, *args, **kwargs)

    monkeypatch.setattr(run_routes, "run_in_threadpool", busy_thread_pool)
    body = {"content": "Explain the topic", "request_id": str(uuid4())}

    stream_until_disconnect(run, body, gone=gone)
    replay = run.client.post(f"/api/conversations/{run.cid}/message/stream", json=body)

    saved = storage.get_conversation(run.cid)["messages"][1]
    events = [json.loads(line[6:]) for line in replay.text.splitlines() if line.startswith("data: ")]
    replayed = next(event["data"] for event in events if event["type"] == "stage1_complete")
    assert [row["model"] for row in saved["stage1"]] == [row["model"] for row in replayed] == [ALPHA, BETA]
