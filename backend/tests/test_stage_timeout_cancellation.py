"""Regression tests: stage-timeout must cancel AND await pending model tasks.

Without awaiting cancelled tasks, asyncio may emit warnings and work may leak beyond the
stage timeout boundary.
"""

import pytest
import asyncio


@pytest.mark.asyncio
async def test_openrouter_stage_timeout_awaits_cancelled_tasks(monkeypatch):
    from .. import openrouter

    created_tasks = []
    real_create_task = openrouter.asyncio.create_task

    def tracking_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    async def slow_query_model(*_args, **_kwargs):
        # Intentionally never returns before stage timeout.
        await openrouter.asyncio.sleep(10)
        return {"content": "late"}

    monkeypatch.setattr(openrouter.asyncio, "create_task", tracking_create_task)
    monkeypatch.setattr(openrouter, "query_model", slow_query_model)

    await openrouter.query_models_with_stage_timeout(
        models=["m1", "m2"],
        messages=[{"role": "user", "content": "hi"}],
        stage="test",
        stage_timeout=0.01,
        min_results=0,
    )

    assert created_tasks, "Test expected tasks to be created"

    done_at_return = [t.done() for t in created_tasks]

    try:
        assert all(done_at_return), "Cancelled tasks should be awaited before returning"
    finally:
        # Cleanup for the red case (current behavior): avoid leaking tasks into other tests.
        for t in created_tasks:
            if not t.done():
                t.cancel()
        await openrouter.asyncio.gather(*created_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_ollama_stage_timeout_awaits_cancelled_tasks(monkeypatch):
    from .. import ollama

    created_tasks = []
    real_create_task = asyncio.create_task

    def tracking_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    async def slow_query_model(*_args, **_kwargs):
        await asyncio.sleep(10)
        return {"content": "late"}

    monkeypatch.setattr(asyncio, "create_task", tracking_create_task)
    monkeypatch.setattr(ollama, "query_model", slow_query_model)

    await ollama.query_models_with_stage_timeout(
        models=["m1", "m2"],
        messages=[{"role": "user", "content": "hi"}],
        stage="test",
        stage_timeout=0.01,
        min_results=0,
    )

    assert created_tasks, "Test expected tasks to be created"

    done_at_return = [t.done() for t in created_tasks]

    try:
        assert all(done_at_return), "Cancelled tasks should be awaited before returning"
    finally:
        for t in created_tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*created_tasks, return_exceptions=True)
