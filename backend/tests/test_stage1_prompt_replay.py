"""The Stage 1 prompt of a council run is kept server-side so /retry-model can replay it."""

import base64
import copy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import config, council, router_dispatch, runtime_settings, storage
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
    assert send(run, endpoint).status_code == 200
    run.template = "CHANGED TEMPLATE {full_query}"
    run.memory = "NEWER_MEMORY_NOTE"
    reads = run.memory_reads

    response = retry(run)

    assert response.status_code == 200, response.text
    assert run.retried == run.sent
    assert {"role": "system", "content": "Relevant past exchanges:\nMEMORY_NOTE_19"} in run.retried[0]
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
