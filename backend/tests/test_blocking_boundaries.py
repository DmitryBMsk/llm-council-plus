"""Slow synchronous integrations must leave the ASGI event loop responsive."""
import asyncio
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from backend import council
from backend.api.routes import auth_routes, drive
from backend.main import app


async def assert_loop_responsive(operation, entered):
    task = asyncio.create_task(operation)
    ticks = 0
    while not entered.is_set():
        await asyncio.sleep(0.001)
    # The operation must still be running after the loop sees entry.
    while not task.done():
        ticks += 1
        await asyncio.sleep(0.005)
    result = await task
    assert ticks >= 3, 'synchronous integration blocked event loop'
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint', ['login', 'drive'])
async def test_slow_http_integration_leaves_loop_responsive(monkeypatch, endpoint):
    entered = threading.Event()

    def slow(*args, **kwargs):
        entered.set()
        time.sleep(0.12)
        return SimpleNamespace(success=True, model_dump=lambda: {'success': True}) if endpoint == 'login' else {'id': 'file'}

    if endpoint == 'login':
        monkeypatch.setattr(auth_routes, 'authenticate', slow)
        path, payload = '/api/auth', {'username': 'alice', 'password': 'password'}
    else:
        monkeypatch.setattr(drive, 'is_drive_configured', lambda: True)
        monkeypatch.setattr(drive, 'upload_to_drive', slow)
        monkeypatch.setattr(council.config, 'AUTH_ENABLED', False)
        path, payload = '/api/drive/upload', {'filename': 'test.md', 'content': 'hello'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await assert_loop_responsive(client.post(path, json=payload), entered)
        assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize('streaming', [False, True])
async def test_memory_init_and_retrieval_leave_loop_responsive(monkeypatch, streaming):
    entered = threading.Event()

    class SlowMemory:
        def __init__(self, _conversation_id):
            entered.set()
            time.sleep(0.06)

        def get_context(self, _query):
            time.sleep(0.06)
            return 'remembered'

    async def query(*args, **kwargs):
        return {'m': {'content': 'answer'}}

    async def stream(*args, **kwargs):
        yield 'm', {'content': 'answer'}

    async def run():
        kwargs = dict(models=['m'], conversation_id='test')
        if streaming:
            return [item async for item in council.stage1_collect_responses_streaming('hello', **kwargs)]
        return await council.stage1_collect_responses('hello', **kwargs)

    monkeypatch.setattr(council, 'CouncilMemorySystem', SlowMemory)
    monkeypatch.setattr(council.config, 'ENABLE_MEMORY', True)
    monkeypatch.setattr(council, 'requires_tools', lambda _query: False)
    monkeypatch.setattr(council.router_dispatch, 'query_models_parallel', query)
    monkeypatch.setattr(council.router_dispatch, 'query_models_streaming', stream)
    await assert_loop_responsive(run(), entered)


@pytest.mark.asyncio
async def test_memory_save_leaves_loop_responsive(monkeypatch):
    entered = threading.Event()

    class SlowMemory:
        def __init__(self, _conversation_id):
            entered.set()
            time.sleep(0.06)

        def save_exchange(self, query, response):
            assert query == 'question' and response == 'final'
            time.sleep(0.06)

    async def stage1(*args, **kwargs):
        return [{'model': 'm', 'response': 'answer'}], []

    async def stage2(*args, **kwargs):
        return [], {}

    async def stage3(*args, **kwargs):
        return {'model': 'm', 'response': 'final'}

    monkeypatch.setattr(council, 'CouncilMemorySystem', SlowMemory)
    monkeypatch.setattr(council.config, 'ENABLE_MEMORY', True)
    monkeypatch.setattr(council, 'stage1_collect_responses', stage1)
    monkeypatch.setattr(council, 'stage2_collect_rankings', stage2)
    monkeypatch.setattr(council, 'stage3_synthesize_final', stage3)
    await assert_loop_responsive(council.run_full_council('question', conversation_id='test'), entered)


def test_embedding_initialization_is_shared_across_concurrent_conversations(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from backend import memory
    calls = []
    embedding = object()

    def create():
        calls.append(1)
        time.sleep(0.02)
        return embedding

    monkeypatch.setattr(memory, '_embeddings_initialized', False)
    monkeypatch.setattr(memory, '_embeddings', None)
    monkeypatch.setattr(memory, '_create_embeddings', create)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: memory.get_embeddings(), range(8)))
    assert results == [embedding] * 8
    assert len(calls) == 1


def test_drive_transport_is_cached_only_within_owning_thread(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from backend import gdrive
    barrier = threading.Barrier(2)
    monkeypatch.setattr(gdrive, '_drive_services', threading.local())
    monkeypatch.setattr(gdrive.config, 'GOOGLE_DRIVE_ENABLED', True)
    monkeypatch.setattr(gdrive.os.path, 'exists', lambda _: True)
    credentials = SimpleNamespace(from_service_account_file=lambda *a, **k: object())
    monkeypatch.setattr(gdrive, 'service_account', SimpleNamespace(Credentials=credentials))
    monkeypatch.setattr(gdrive, 'MediaIoBaseUpload', object())
    monkeypatch.setattr(gdrive, 'build', lambda *a, **k: object())

    def get_twice():
        first = gdrive.get_drive_service()
        barrier.wait(timeout=3)
        assert first is gdrive.get_drive_service()
        return first

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: get_twice(), range(2)))
    assert results[0] is not results[1]


@pytest.mark.asyncio
async def test_shared_memory_model_never_used_concurrently(monkeypatch):
    active = 0
    max_active = 0

    class Memory:
        def __init__(self, conversation_id):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            time.sleep(0.01)

        def get_context(self, query):
            nonlocal active
            time.sleep(0.02)
            active -= 1
            return 'context'

    monkeypatch.setattr(council, 'CouncilMemorySystem', Memory)
    results = await asyncio.gather(*[
        council.run_in_threadpool(council._read_memory_context, str(i), 'query')
        for i in range(6)
    ])
    assert results == ['context'] * 6
    assert max_active == 1
