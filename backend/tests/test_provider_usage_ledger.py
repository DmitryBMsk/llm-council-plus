"""Provider accounting tracks observations, never estimates missing prices."""
import asyncio
import pytest
from backend import usage


@pytest.mark.asyncio
async def test_ledger_shared_by_children_and_isolated_between_runs():
    async def run(model):
        token = usage.begin_provider_usage()
        try:
            async def child():
                with usage.stage_scope('STAGE1'):
                    usage.record_usage('openrouter', model, {'prompt_tokens': 0, 'completion_tokens': 3, 'total_tokens': 3, 'cost': 0.02})
            await asyncio.create_task(child())
            return usage.get_provider_usage()
        finally:
            usage.end_provider_usage(token)
    first, second = await asyncio.gather(run('a'), run('b'))
    assert [entry['model'] for entry in first['entries']] == ['a']
    assert [entry['model'] for entry in second['entries']] == ['b']
    assert first['entries'][0]['stage'] == 'STAGE1'
    assert first['totals']['prompt_tokens'] == 0
    assert first['totals']['provider_cost'] == 0.02
    assert usage.get_provider_usage()['entries'] == []


def test_missing_usage_and_retries_do_not_invent_zero_cost():
    token = usage.begin_provider_usage()
    try:
        usage.record_usage('openrouter', 'a', None, stage='STAGE3', outcome='error')
        usage.record_usage('openrouter', 'b', {'prompt_tokens': 7}, stage='STAGE3_FALLBACK')
        usage.record_usage('ollama', 'title', {'prompt_tokens': 2, 'completion_tokens': 1}, stage='TITLE')
        report = usage.get_provider_usage()
    finally:
        usage.end_provider_usage(token)
    assert len(report['entries']) == 3
    assert report['totals']['prompt_tokens'] == 9
    assert report['totals']['completion_tokens'] == 1
    assert report['totals']['provider_cost'] is None
    assert report['coverage']['prompt_tokens'] == 2
    assert report['coverage']['provider_cost'] == 0
    assert report['complete'] is False


def test_invalid_numbers_are_unknown_and_result_is_detached():
    token = usage.begin_provider_usage()
    original = {'prompt_tokens': -1, 'completion_tokens': True, 'total_tokens': float('nan'), 'cost': float('inf')}
    try:
        usage.record_usage('openrouter', 'a', original)
        original['prompt_tokens'] = 100
        report = usage.get_provider_usage()
        assert all(value is None for value in report['totals'].values())
        report['entries'].clear()
        assert len(usage.get_provider_usage()['entries']) == 1
    finally:
        usage.end_provider_usage(token)


def test_stage_result_fallback_labels_scope_and_preserves_models():
    report = usage.collect_provider_usage(
        [{'model': 'a', 'usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}}],
        [{'model': 'b', 'error': True}],
        {'model': 'chair', 'usage': {'cost': 0.01}},
    )
    assert report['scope'] == 'stage_results_only'
    assert [(entry['stage'], entry['model']) for entry in report['entries']] == [
        ('STAGE1', 'a'), ('STAGE2', 'b'), ('STAGE3', 'chair')]
    assert report['totals']['total_tokens'] == 5


@pytest.mark.asyncio
async def test_http_retry_and_success_each_record_attempt(monkeypatch):
    import httpx
    from backend import config, openrouter
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', 'test-only')
    monkeypatch.setattr(openrouter, 'INITIAL_BACKOFF_SECONDS', 0)
    responses = [httpx.Response(429, json={'error': {'message': 'retry'}}),
                 httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}],
                                          'usage': {'total_tokens': 7, 'cost': 0.03}})]
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(lambda request: responses.pop(0)), **kwargs))
    token = usage.begin_provider_usage()
    try:
        await openrouter.query_model('model', [], stage='STAGE3')
        report = usage.get_provider_usage()
    finally:
        usage.end_provider_usage(token)
    assert [item['outcome'] for item in report['entries']] == ['error', 'success']
    assert report['totals']['provider_cost'] == 0.03
    assert report['coverage']['provider_cost'] == 1


@pytest.mark.asyncio
async def test_expired_lease_prevents_provider_http(monkeypatch):
    import httpx
    from backend import config, openrouter, run_context
    monkeypatch.setattr(config, 'OPENROUTER_API_KEY', 'test-only')
    class Expired:
        def ensure_active(self):
            raise RuntimeError('expired lease')
    def forbidden(**kwargs):
        pytest.fail('HTTP client created after lease expiry')
    monkeypatch.setattr(httpx, 'AsyncClient', forbidden)
    token = run_context.active_ticket.set(Expired())
    try:
        with pytest.raises(RuntimeError, match='expired lease'):
            await openrouter.query_model('model', [])
    finally:
        run_context.active_ticket.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['stage1', 'stream', 'stage2', 'stage3'])
async def test_council_outputs_preserve_reported_usage(monkeypatch, stage):
    from backend import council
    values = {'prompt_tokens': 2, 'completion_tokens': 1, 'total_tokens': 3, 'cost': 0.001}
    response = {'content': 'FINAL RANKING:\n1. Response A', 'usage': values}
    async def parallel(*args, **kwargs):
        return {'m': response}
    async def single(*args, **kwargs):
        return response
    async def stream(*args, **kwargs):
        yield 'm', response
    monkeypatch.setattr(council.config, 'ENABLE_MEMORY', False)
    monkeypatch.setattr(council, 'requires_tools', lambda _: False)
    monkeypatch.setattr(council.router_dispatch, 'query_models_parallel', parallel)
    monkeypatch.setattr(council.router_dispatch, 'query_models_streaming', stream)
    monkeypatch.setattr(council.router_dispatch, 'query_models_with_stage_timeout', parallel)
    monkeypatch.setattr(council.router_dispatch, 'query_model', single)
    if stage == 'stage1':
        output = (await council.stage1_collect_responses('hello', models=['m']))[0][0]
    elif stage == 'stream':
        output = [item async for item in council.stage1_collect_responses_streaming('hello', models=['m'])][0]
    elif stage == 'stage2':
        output = (await council.stage2_collect_rankings('hello', [{'model': 'm', 'response': 'ok'}], models=['m']))[0][0]
    else:
        output = await council.stage3_synthesize_final('hello', [{'model': 'm', 'response': 'ok'}], [], chairman='m')
    assert output['usage'] == values


@pytest.mark.asyncio
async def test_ollama_parallel_dispatch_labels_child_attempts(monkeypatch):
    import httpx
    from backend import router_dispatch
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            'message': {'content': 'ok'}, 'prompt_eval_count': 3, 'eval_count': 1})), **kwargs))
    token = usage.begin_provider_usage()
    try:
        await router_dispatch.query_models_parallel('ollama', ['a', 'b'], [], stage='STAGE2')
        report = usage.get_provider_usage()
    finally:
        usage.end_provider_usage(token)
    assert sorted(entry['model'] for entry in report['entries']) == ['a', 'b']
    assert all(entry['stage'] == 'STAGE2' for entry in report['entries'])
    assert report['totals']['total_tokens'] == 8


@pytest.mark.asyncio
async def test_streaming_scope_restored_before_yield_and_can_close_elsewhere(monkeypatch):
    from backend import router_dispatch
    async def provider(**kwargs):
        usage.record_usage('ollama', 'a', {'total_tokens': 1})
        yield 'a', {'content': 'ok'}
    monkeypatch.setattr(router_dispatch.ollama, 'query_models_streaming', provider)
    token = usage.begin_provider_usage()
    try:
        stream = router_dispatch.query_models_streaming('ollama', ['a'], [])
        await stream.__anext__()
        usage.record_usage('ollama', 'outside', {'total_tokens': 1})
        await asyncio.create_task(stream.aclose())
        entries = usage.get_provider_usage()['entries']
    finally:
        usage.end_provider_usage(token)
    assert [entry['stage'] for entry in entries] == ['STAGE1', None]
