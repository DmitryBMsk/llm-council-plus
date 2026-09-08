"""Explicit one-model continuation, with preserved originals and idempotency."""

import copy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from backend import config, storage, router_dispatch
from backend.main import app
from backend.api.deps import get_current_user


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "conversations"))
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(storage, "is_using_database", lambda: False)
    model = "anthropic/test-model"
    cid = str(uuid4())
    storage.create_conversation(
        cid,
        models=[model, "other/model"],
        chairman=model,
        router_type="openrouter",
        username="alice",
        system_prompt="Original policy",
    )
    storage.add_user_message(cid, "Explain the original topic")
    query = AsyncMock(
        return_value={
            "content": "tinued answer.",
            "finish_reason": "stop",
            "truncated": False,
            "generation_id": "generation-cont",
            "usage": {"completion_tokens": 10},
        }
    )
    monkeypatch.setattr(router_dispatch, "query_model", query)
    return TestClient(app), cid, model, query


@pytest.mark.parametrize("stage", ["stage1", "stage2", "stage3"])
def test_explicit_continuation_only_queries_selected_model_and_keeps_original(context, stage):
    client, cid, model, query = context
    record = {"model": model, "truncated": True, "finish_reason": "length", "response": "Con"}
    if stage == "stage2":
        record = {"model": model, "truncated": True, "finish_reason": "length", "ranking": "Con", "parsed_ranking": []}
    source = {
        "stage1": [record] if stage == "stage1" else [{"model": model, "response": "first answer"}],
        "stage2": [record] if stage == "stage2" else None,
        "stage3": record if stage == "stage3" else None,
        "metadata": {"label_to_model": {"Response A": model}},
    }
    storage.add_assistant_message(cid, **source)
    original = copy.deepcopy(storage.get_conversation(cid)["messages"])
    body = {"message_index": 1, "stage": stage, "model": model, "request_id": str(uuid4())}
    response = client.post(f"/api/conversations/{cid}/continue", json=body)
    assert response.status_code == 200, response.text
    assert query.await_count == 1
    assert query.call_args.kwargs["model"] == model
    assert query.call_args.kwargs["stage"] == "CONTINUATION"
    if stage != "stage1":
        assert "Response A" in str(query.call_args.kwargs["messages"])
    assert any(m["role"] == "assistant" and m["content"] == "Con" for m in query.call_args.kwargs["messages"])
    saved = storage.get_conversation(cid)["messages"]
    assert saved[:2] == original
    assert len(saved) == 4
    target = saved[-1][stage]
    row = target[0] if isinstance(target, list) else target
    assert row.get("response", row.get("ranking")) == "Continued answer."
    assert saved[-1]["metadata"]["continuation_of"]["message_index"] == 1
    repeated = client.post(f"/api/conversations/{cid}/continue", json=body)
    assert repeated.json() == response.json()
    assert query.await_count == 1
    assert len(storage.get_conversation(cid)["messages"]) == 4


def test_legacy_limit_hit_can_be_continued_but_explicit_stop_cannot(context):
    client, cid, model, query = context
    storage.add_assistant_message(cid, [{"model": model, "response": "Con", "usage": {"completion_tokens": 8192}}])
    request = {"message_index": 1, "stage": "stage1", "model": model, "request_id": str(uuid4())}
    assert client.post(f"/api/conversations/{cid}/continue", json=request).status_code == 200
    # A known stop overrides the numerical coincidence at a limit.
    storage.add_user_message(cid, "Next")
    storage.add_assistant_message(
        cid, [{"model": model, "response": "Complete", "finish_reason": "stop", "usage": {"completion_tokens": 8192}}]
    )
    assert (
        client.post(
            f"/api/conversations/{cid}/continue", json={**request, "message_index": 5, "request_id": str(uuid4())}
        ).status_code
        == 409
    )
    assert query.await_count == 1


def test_invalid_source_and_ownership_do_not_call_provider(context, monkeypatch):
    client, cid, model, query = context
    storage.add_assistant_message(cid, [{"model": model, "response": "Complete", "finish_reason": "stop"}])
    body = {"message_index": 1, "stage": "stage1", "model": model, "request_id": str(uuid4())}
    assert client.post(f"/api/conversations/{cid}/continue", json=body).status_code == 409
    assert (
        client.post(
            f"/api/conversations/{cid}/continue", json={**body, "model": "wrong", "request_id": str(uuid4())}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/conversations/{cid}/continue", json={**body, "message_index": 0, "request_id": str(uuid4())}
        ).status_code
        == 422
    )
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    app.dependency_overrides[get_current_user] = lambda: "bob"
    try:
        assert client.post(f"/api/conversations/{cid}/continue", json=body).status_code == 404
    finally:
        app.dependency_overrides.clear()
    assert query.await_count == 0


def test_failed_continuation_does_not_append_or_replace_any_message(context):
    client, cid, model, query = context
    storage.add_assistant_message(cid, [{"model": model, "response": "Con", "truncated": True}])
    original = storage.get_conversation(cid)["messages"]
    query.return_value = {"error": True, "error_type": "http", "error_message": "Insufficient credits"}
    response = client.post(
        f"/api/conversations/{cid}/continue",
        json={"message_index": 1, "stage": "stage1", "model": model, "request_id": str(uuid4())},
    )
    assert response.status_code == 502
    assert storage.get_conversation(cid)["messages"] == original


def test_chained_continuations_reuse_original_question_and_extracted_document(context):
    client, cid, model, query = context
    # Attachments are stored as extracted text, independent of later user labels.
    storage._json_update_conversation(
        cid,
        lambda c: c["messages"][0].update(
            attachments=[{"file_type": "txt", "filename": "source.txt", "content": "DOCUMENT_ORIGINAL_42"}]
        ),
    )
    storage.add_assistant_message(cid, [{"model": model, "response": "Con", "truncated": True}])
    query.side_effect = [
        {"content": "tinued", "finish_reason": "length", "truncated": True},
        {"content": " answer.", "finish_reason": "stop", "truncated": False},
    ]
    base = {"stage": "stage1", "model": model}
    assert (
        client.post(
            f"/api/conversations/{cid}/continue", json={**base, "message_index": 1, "request_id": str(uuid4())}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/conversations/{cid}/continue", json={**base, "message_index": 3, "request_id": str(uuid4())}
        ).status_code
        == 200
    )
    second_messages = query.call_args.kwargs["messages"]
    assert "Explain the original topic" in second_messages[1]["content"]
    assert "DOCUMENT_ORIGINAL_42" in second_messages[1]["content"]
    assert storage.get_conversation(cid)["messages"][5]["stage1"][0]["response"] == "Continued answer."


def test_empty_truncated_followup_keeps_original_dialogue_context(context):
    client, cid, model, query = context
    storage._json_update_conversation(cid, lambda c: c["messages"][0].update(content="Remember UNIQUE_CONTEXT_174"))
    storage.add_assistant_message(cid, [{"model": model, "response": "I remember."}])
    storage.add_user_message(cid, "Explain that project in depth")
    storage.add_assistant_message(cid, [{"model": model, "response": "", "truncated": True, "finish_reason": "length"}])
    response = client.post(
        f"/api/conversations/{cid}/continue",
        json={"message_index": 3, "stage": "stage1", "model": model, "request_id": str(uuid4())},
    )
    assert response.status_code == 200
    assert "UNIQUE_CONTEXT_174" in str(query.call_args.kwargs["messages"])


def test_continuation_usage_and_ids_survive_reload(context):
    client, cid, model, query = context
    from backend.usage import record_usage

    async def paid(*args, **kwargs):
        record_usage("openrouter", model, {"completion_tokens": 10, "cost": 0.01}, stage="CONTINUATION")
        return {
            "content": "tinued.",
            "finish_reason": "stop",
            "truncated": False,
            "usage": {"completion_tokens": 10, "cost": 0.01},
        }

    query.side_effect = paid
    storage.add_assistant_message(cid, [{"model": model, "response": "Con", "truncated": True}])
    rid = str(uuid4())
    response = client.post(
        f"/api/conversations/{cid}/continue",
        json={"message_index": 1, "stage": "stage1", "model": model, "request_id": rid},
    )
    assert response.status_code == 200
    saved = storage.get_conversation(cid)["messages"][-1]["metadata"]
    assert saved["request_id"] == rid
    assert saved["run_id"] == response.json()["metadata"]["run_id"]
    assert saved["provider_usage"]["totals"]["provider_cost"] == 0.01


def test_sql_continuation_appends_pair_atomically(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.database import Base

    engine = create_engine(f"sqlite:///{tmp_path}/continuations.db")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(storage, "is_using_database", lambda: True)
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    query = AsyncMock(return_value={"content": "tinued.", "finish_reason": "stop", "truncated": False})
    monkeypatch.setattr(router_dispatch, "query_model", query)
    cid = str(uuid4())
    try:
        storage.create_conversation(cid, models=["a"], router_type="openrouter")
        storage.add_user_message(cid, "Original question")
        storage.add_assistant_message(cid, [], stage3={"model": "a", "response": "Con", "truncated": True})
        result = TestClient(app).post(
            f"/api/conversations/{cid}/continue",
            json={"message_index": 1, "stage": "stage3", "model": "a", "request_id": str(uuid4())},
        )
        assert result.status_code == 200, result.text
        messages = storage.get_conversation(cid)["messages"]
        assert len(messages) == 4
        assert messages[1]["stage3"]["response"] == "Con"
        assert messages[3]["stage3"]["response"] == "Continued."
    finally:
        engine.dispose()


@pytest.mark.parametrize("stage,directive", [("stage2", "FINAL RANKING"), ("stage3", "chairman")])
def test_reasoning_only_continuation_retains_stage_task(context, stage, directive):
    client, cid, model, query = context
    record = {"model": model, "truncated": True, "finish_reason": "length"}
    record["ranking" if stage == "stage2" else "response"] = ""
    source = {
        "stage1": [{"model": model, "response": "Candidate answer"}],
        "stage2": [record] if stage == "stage2" else [],
        "stage3": record if stage == "stage3" else None,
        "metadata": {"label_to_model": {"Response A": model}, "tool_outputs": [{"result": "STORED_EVIDENCE_912"}]},
    }
    storage.add_assistant_message(cid, **source)
    reply = client.post(
        f"/api/conversations/{cid}/continue",
        json={"message_index": 1, "stage": stage, "model": model, "request_id": str(uuid4())},
    )
    assert reply.status_code == 200
    prompt = query.call_args.kwargs["messages"]
    assert directive in prompt[-1]["content"]
    assert "STORED_EVIDENCE_912" in str(prompt)
