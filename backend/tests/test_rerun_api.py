"""Explicit partial reruns: one failed Stage 1 model, or the final answer only."""

import copy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from backend import config, storage, router_dispatch
from backend.main import app
from backend.api.deps import get_current_user
from backend.usage import record_usage

ALPHA, BETA, CHAIR = "a/alpha", "b/beta", "c/chair"


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "conversations"))
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(storage, "is_using_database", lambda: False)
    cid = str(uuid4())
    storage.create_conversation(
        cid,
        models=[ALPHA, BETA],
        chairman=CHAIR,
        router_type="openrouter",
        username="alice",
        system_prompt="Original policy",
    )
    storage.add_user_message(cid, "Explain the original topic")
    storage.add_assistant_message(
        cid,
        [
            {"model": ALPHA, "error": True, "error_type": "timeout", "error_message": "Request timed out"},
            {"model": BETA, "response": "BETA_ANSWER_77"},
        ],
        [{"model": BETA, "ranking": "RANKING_NOTE_31\nFINAL RANKING:\n1. Response A", "parsed_ranking": ["Response A"]}],
        {"model": CHAIR, "response": "First synthesis"},
        {"label_to_model": {"Response A": BETA}, "tool_outputs": [{"tool": "search", "result": "STORED_EVIDENCE_55"}]},
    )

    async def paid(*args, **kwargs):
        record_usage("openrouter", kwargs["model"], {"completion_tokens": 10, "cost": 0.01}, stage=kwargs["stage"])
        return {"content": "Fresh answer", "finish_reason": "stop", "truncated": False}

    query = AsyncMock(side_effect=paid)
    monkeypatch.setattr(router_dispatch, "query_model", query)
    return TestClient(app), cid, query


def messages_of(cid):
    return storage.get_conversation(cid)["messages"]


def test_retry_asks_only_the_failed_model_and_keeps_the_source_message(context):
    client, cid, query = context
    original = copy.deepcopy(messages_of(cid))
    body = {"message_index": 1, "model": ALPHA, "request_id": str(uuid4())}

    response = client.post(f"/api/conversations/{cid}/retry-model", json=body)

    assert response.status_code == 200, response.text
    assert query.await_count == 1
    assert query.call_args.kwargs["model"] == ALPHA
    assert query.call_args.kwargs["stage"] == "STAGE1"
    # One click is one provider request: a 429 is reported, not resent with backoff
    assert query.call_args.kwargs["retry_on_rate_limit"] is False
    prompt = query.call_args.kwargs["messages"]
    assert prompt[0] == {"role": "system", "content": "Original policy"}
    assert "Explain the original topic" in str(prompt)
    assert "STORED_EVIDENCE_55" in str(prompt)
    saved = messages_of(cid)
    assert saved[:2] == original
    assert len(saved) == 4
    assert saved[2]["role"] == "user"
    retried = saved[3]
    assert [(row["model"], row["response"]) for row in retried["stage1"]] == [(ALPHA, "Fresh answer")]
    assert not retried.get("stage2") and not retried.get("stage3")
    assert retried["metadata"]["retry_of"] == {"message_index": 1, "stage": "stage1", "model": ALPHA}
    assert retried["metadata"]["provider_usage"]["totals"]["provider_cost"] == 0.01
    assert retried["metadata"]["request_id"] == body["request_id"]

    repeated = client.post(f"/api/conversations/{cid}/retry-model", json=body)

    assert repeated.json() == response.json()
    assert query.await_count == 1
    assert len(messages_of(cid)) == 4


def test_regenerate_reruns_only_stage3_with_the_chosen_chairman(context):
    client, cid, query = context
    original = copy.deepcopy(messages_of(cid))
    body = {"message_index": 1, "chairman": BETA, "request_id": str(uuid4())}

    response = client.post(f"/api/conversations/{cid}/regenerate", json=body)

    assert response.status_code == 200, response.text
    assert query.await_count == 1
    assert query.call_args.kwargs["model"] == BETA
    assert query.call_args.kwargs["stage"] == "STAGE3"
    prompt = str(query.call_args.kwargs["messages"])
    for stored in ("Explain the original topic", "BETA_ANSWER_77", "RANKING_NOTE_31", "STORED_EVIDENCE_55"):
        assert stored in prompt
    saved = messages_of(cid)
    assert saved[:2] == original
    assert len(saved) == 4
    regenerated = saved[3]
    assert (regenerated["stage3"]["model"], regenerated["stage3"]["response"]) == (BETA, "Fresh answer")
    assert not regenerated.get("stage1") and not regenerated.get("stage2")
    assert regenerated["metadata"]["retry_of"] == {"message_index": 1, "stage": "stage3", "model": BETA}
    assert regenerated["metadata"]["provider_usage"]["totals"]["provider_cost"] == 0.01

    repeated = client.post(f"/api/conversations/{cid}/regenerate", json=body)

    assert repeated.json() == response.json()
    assert query.await_count == 1
    assert len(messages_of(cid)) == 4


def test_regenerate_defaults_to_the_conversation_chairman(context):
    client, cid, query = context

    response = client.post(
        f"/api/conversations/{cid}/regenerate", json={"message_index": 1, "request_id": str(uuid4())}
    )

    assert response.status_code == 200, response.text
    assert query.call_args.kwargs["model"] == CHAIR
    assert messages_of(cid)[3]["metadata"]["retry_of"]["model"] == CHAIR


@pytest.mark.parametrize(
    "route,change,status",
    [
        ("retry-model", {"message_index": 0}, 422),  # a user message
        ("retry-model", {"message_index": 9}, 422),  # no such message
        ("retry-model", {"model": BETA}, 409),  # answered, did not fail
        ("retry-model", {"model": "x/unknown"}, 404),
        ("retry-model", {"message_index": True}, 422),  # JSON true must not be read as index 1
        ("regenerate", {"message_index": 0}, 422),
        ("regenerate", {"message_index": True}, 422),
        ("regenerate", {"chairman": "x/outsider"}, 422),
    ],
)
def test_invalid_reruns_are_rejected_without_calling_a_provider(context, route, change, status):
    client, cid, query = context
    body = {"message_index": 1, "request_id": str(uuid4()), **({"model": ALPHA} if route == "retry-model" else {})}

    assert client.post(f"/api/conversations/{cid}/{route}", json={**body, **change}).status_code == status
    assert query.await_count == 0


@pytest.mark.parametrize("route,extra", [("retry-model", {"model": ALPHA}), ("regenerate", {})])
def test_reruns_are_refused_for_a_conversation_of_another_user(context, monkeypatch, route, extra):
    client, cid, query = context
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    app.dependency_overrides[get_current_user] = lambda: "bob"
    try:
        body = {"message_index": 1, "request_id": str(uuid4()), **extra}
        assert client.post(f"/api/conversations/{cid}/{route}", json=body).status_code == 404
    finally:
        app.dependency_overrides.clear()
    assert query.await_count == 0


@pytest.mark.parametrize("route,extra", [("retry-model", {"model": ALPHA}), ("regenerate", {})])
def test_failed_rerun_stores_nothing(context, route, extra):
    client, cid, query = context
    original = messages_of(cid)
    query.side_effect = None
    query.return_value = {"error": True, "error_type": "http", "error_message": "Insufficient credits"}

    response = client.post(
        f"/api/conversations/{cid}/{route}", json={"message_index": 1, "request_id": str(uuid4()), **extra}
    )

    assert response.status_code == 502
    assert response.json()["detail"]["status"] == "failed"
    assert messages_of(cid) == original


def test_reruns_of_a_rerun_go_back_to_the_original_council_message(context):
    client, cid, query = context
    first = client.post(f"/api/conversations/{cid}/regenerate", json={"message_index": 1, "request_id": str(uuid4())})
    assert first.status_code == 200, first.text

    again = client.post(
        f"/api/conversations/{cid}/regenerate", json={"message_index": 3, "chairman": BETA, "request_id": str(uuid4())}
    )

    assert again.status_code == 200, again.text
    prompt = str(query.call_args.kwargs["messages"])
    assert "Explain the original topic" in prompt and "BETA_ANSWER_77" in prompt
    assert messages_of(cid)[5]["metadata"]["retry_of"] == {"message_index": 3, "stage": "stage3", "model": BETA}


def test_truncated_retry_is_continued_with_the_original_question(context):
    client, cid, query = context
    query.side_effect = None
    query.return_value = {"content": "Fre", "finish_reason": "length", "truncated": True}
    retry = {"message_index": 1, "model": ALPHA, "request_id": str(uuid4())}
    assert client.post(f"/api/conversations/{cid}/retry-model", json=retry).status_code == 200
    query.return_value = {"content": "sh answer", "finish_reason": "stop", "truncated": False}

    continued = client.post(
        f"/api/conversations/{cid}/continue",
        json={"message_index": 3, "stage": "stage1", "model": ALPHA, "request_id": str(uuid4())},
    )

    assert continued.status_code == 200, continued.text
    assert "Explain the original topic" in str(query.call_args.kwargs["messages"])
    assert messages_of(cid)[5]["stage1"][0]["response"] == "Fresh answer"


def test_request_id_reused_with_another_chairman_is_a_conflict_not_a_replay(context):
    client, cid, query = context
    body = {"message_index": 1, "chairman": BETA, "request_id": str(uuid4())}
    assert client.post(f"/api/conversations/{cid}/regenerate", json=body).status_code == 200

    other = client.post(f"/api/conversations/{cid}/regenerate", json={**body, "chairman": CHAIR})

    assert other.status_code == 409, other.text
    assert other.json()["detail"]["code"] == "idempotency_conflict"
    assert query.await_count == 1
    assert len(messages_of(cid)) == 4


@pytest.mark.parametrize("route,extra", [("retry-model", {"model": ALPHA}), ("regenerate", {})])
def test_oversized_rerun_context_is_rejected_without_calling_a_provider(context, route, extra):
    client, cid, query = context
    storage._json_update_conversation(
        cid,
        lambda c: c["messages"][0].update(
            attachments=[{"file_type": "txt", "filename": "big.txt", "content": "x" * 500_001}]
        ),
    )

    response = client.post(
        f"/api/conversations/{cid}/{route}", json={"message_index": 1, "request_id": str(uuid4()), **extra}
    )

    assert response.status_code == 422, response.text
    assert query.await_count == 0
    assert len(messages_of(cid)) == 2
