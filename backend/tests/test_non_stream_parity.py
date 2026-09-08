"""Parity tests for the non-stream conversation message endpoint."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient


@pytest.mark.asyncio
async def test_stage1_non_stream_injects_custom_system_prompt(monkeypatch):
    """The non-stream Stage 1 request must give the custom prompt top priority."""
    from backend import council

    captured = {}

    async def fake_query_models_parallel(router_type, models, messages, **kwargs):
        captured.update(
            router_type=router_type,
            models=models,
            messages=messages,
        )
        return {"model-a": {"content": "answer"}}

    monkeypatch.setattr(council.config, "ENABLE_MEMORY", False)
    monkeypatch.setattr(council, "requires_tools", lambda _query: False)
    monkeypatch.setattr(
        council.router_dispatch,
        "query_models_parallel",
        fake_query_models_parallel,
    )

    results, tool_outputs = await council.stage1_collect_responses(
        "Question",
        models=["model-a"],
        router_type="ollama",
        system_prompt="Follow the custom policy",
    )

    assert captured == {
        "router_type": "ollama",
        "models": ["model-a"],
        "messages": [
            {"role": "system", "content": "Follow the custom policy"},
            {"role": "user", "content": "Question"},
        ],
    }
    assert results == [{"model": "model-a", "response": "answer"}]
    assert tool_outputs == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("execution_mode", "expected_stages"),
    [
        ("chat_only", ["stage1"]),
        ("chat_ranking", ["stage1", "stage2"]),
        ("full", ["stage1", "stage2", "stage3"]),
    ],
)
async def test_run_full_council_honors_execution_mode_and_overrides(
    monkeypatch,
    execution_mode,
    expected_stages,
):
    """The non-stream orchestrator must use stored settings and stop on mode."""
    from backend import council

    calls = []
    stage1_results = [{"model": "model-a", "response": "answer"}]
    tool_outputs = [{"tool": "calculator", "result": "4"}]
    stage2_results = [
        {"model": "model-a", "ranking": "FINAL RANKING:\n1. Response A"}
    ]
    label_to_model = {"Response A": "model-a"}
    stage3_result = {"model": "chairman-a", "response": "final"}
    token_stats = {"total": 12, "input": 7, "output": 5}

    async def fake_stage1(
        user_query,
        conversation_history=None,
        models=None,
        images=None,
        conversation_id=None,
        router_type=None,
        system_prompt=None,
    ):
        calls.append(
            (
                "stage1",
                {
                    "models": models,
                    "router_type": router_type,
                    "system_prompt": system_prompt,
                },
            )
        )
        return stage1_results, tool_outputs

    async def fake_stage2(
        user_query,
        received_stage1,
        models=None,
        router_type=None,
    ):
        assert received_stage1 == stage1_results
        calls.append(
            ("stage2", {"models": models, "router_type": router_type})
        )
        return stage2_results, label_to_model

    async def fake_stage3(
        user_query,
        received_stage1,
        received_stage2,
        chairman=None,
        tool_outputs=None,
        router_type=None,
    ):
        assert received_stage1 == stage1_results
        assert received_stage2 == stage2_results
        calls.append(
            (
                "stage3",
                {
                    "chairman": chairman,
                    "router_type": router_type,
                    "tool_outputs": tool_outputs,
                },
            )
        )
        return stage3_result

    monkeypatch.setattr(council, "stage1_collect_responses", fake_stage1)
    monkeypatch.setattr(council, "stage2_collect_rankings", fake_stage2)
    monkeypatch.setattr(council, "stage3_synthesize_final", fake_stage3)
    monkeypatch.setattr(council, "get_token_stats", lambda: token_stats)
    monkeypatch.setattr(council.config, "ENABLE_MEMORY", False)

    result = await council.run_full_council(
        "Question",
        conversation_history=[{"role": "user", "content": "Earlier"}],
        conversation_id="conversation-1",
        models=["model-a"],
        chairman="chairman-a",
        router_type="ollama",
        system_prompt="Follow the custom policy",
        execution_mode=execution_mode,
    )

    assert [stage for stage, _kwargs in calls] == expected_stages
    assert calls[0][1] == {
        "models": ["model-a"],
        "router_type": "ollama",
        "system_prompt": "Follow the custom policy",
    }
    if "stage2" in expected_stages:
        assert calls[1][1] == {
            "models": ["model-a"],
            "router_type": "ollama",
        }
    if "stage3" in expected_stages:
        assert calls[2][1] == {
            "chairman": "chairman-a",
            "router_type": "ollama",
            "tool_outputs": tool_outputs,
        }

    returned_stage1, returned_stage2, returned_stage3, metadata = result
    assert returned_stage1 == stage1_results
    assert returned_stage2 == (
        stage2_results if "stage2" in expected_stages else None
    )
    assert returned_stage3 == (
        stage3_result if "stage3" in expected_stages else None
    )
    if execution_mode != "full":
        assert metadata["execution_mode"] == execution_mode
    assert metadata["tool_outputs"] == tool_outputs
    assert metadata["token_stats"] == token_stats


@pytest.mark.asyncio
async def test_chat_ranking_with_no_responses_does_not_fabricate_stage3_error(
    monkeypatch,
):
    """An empty ranking run must still stop after Stage 2 like streaming does."""
    from backend import council

    calls = []

    async def fake_stage1(*_args, **_kwargs):
        calls.append("stage1")
        return [], []

    async def fake_stage2(*_args, **_kwargs):
        calls.append("stage2")
        return [], {}

    async def stage3_must_not_run(*_args, **_kwargs):
        pytest.fail("Stage 3 must not run in chat_ranking mode")

    monkeypatch.setattr(council, "stage1_collect_responses", fake_stage1)
    monkeypatch.setattr(council, "stage2_collect_rankings", fake_stage2)
    monkeypatch.setattr(council, "stage3_synthesize_final", stage3_must_not_run)
    monkeypatch.setattr(council, "get_token_stats", lambda: {})

    result = await council.run_full_council(
        "Question",
        execution_mode="chat_ranking",
    )

    assert calls == ["stage1", "stage2"]
    assert result == (
        [],
        [],
        None,
        {
            "execution_mode": "chat_ranking",
            "label_to_model": {},
            "aggregate_rankings": [],
            "tool_outputs": [],
            "token_stats": {},
        },
    )


def test_non_stream_http_route_passes_stored_settings_and_title_router(
    tmp_path,
    monkeypatch,
):
    """The HTTP route must hand all stored conversation settings to the council."""
    from backend import config, storage
    from backend.api.routes import conversations as conversation_routes
    from backend.main import app

    captured = {}
    stage1_results = [{"model": "model-a", "response": "answer"}]
    metadata = {
        "execution_mode": "chat_only",
        "tool_outputs": [],
        "token_stats": {},
    }

    async def fake_run_full_council(user_query, conversation_history=None, **kwargs):
        captured["council"] = {
            "user_query": user_query,
            "conversation_history": conversation_history,
            **kwargs,
        }
        return stage1_results, None, None, metadata

    async def fake_generate_title(user_query, router_type=None):
        captured["title"] = {
            "user_query": user_query,
            "router_type": router_type,
        }
        return "Generated title"

    monkeypatch.setattr(storage, "is_using_database", lambda: False)
    monkeypatch.setattr(storage.config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(conversation_routes, "_models_cache", {})
    monkeypatch.setattr(
        conversation_routes,
        "run_full_council",
        fake_run_full_council,
    )
    monkeypatch.setattr(
        conversation_routes,
        "generate_conversation_title",
        fake_generate_title,
    )

    client = TestClient(app)
    created_response = client.post(
        "/api/conversations",
        json={
            "models": ["model-a"],
            "chairman": "chairman-a",
            "execution_mode": "chat_only",
            "router_type": "ollama",
            "system_prompt": "Follow the custom policy",
        },
    )
    assert created_response.status_code == 200
    conversation_id = created_response.json()["id"]

    message_response = client.post(
        f"/api/conversations/{conversation_id}/message",
        json={"content": "Question"},
    )
    assert message_response.status_code == 200
    assert message_response.json() == {
        "stage1": stage1_results,
        "stage2": None,
        "stage3": None,
        "metadata": metadata,
    }

    assert captured == {
        "council": {
            "user_query": "Question",
            "conversation_history": [],
            "images": None,
            "conversation_id": conversation_id,
            "models": ["model-a"],
            "chairman": "chairman-a",
            "router_type": "ollama",
            "system_prompt": "Follow the custom policy",
            "execution_mode": "chat_only",
        },
        "title": {
            "user_query": "Question",
            "router_type": "ollama",
        },
    }
