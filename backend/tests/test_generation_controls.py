from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from backend import openrouter, ollama, runtime_settings


@pytest.mark.asyncio
@pytest.mark.parametrize('reason,expected', [('length', True), ('stop', False), (None, None)])
async def test_openrouter_retains_authoritative_finish(monkeypatch, reason, expected):
    monkeypatch.setattr(openrouter.config, 'OPENROUTER_API_KEY', 'test-only')
    async def post(self, url, **kwargs):
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'id': 'generation-test', 'choices': [{'finish_reason': reason,
            'native_finish_reason': reason, 'message': {'content': ''}}],
            'usage': {'completion_tokens': 8192}})
    with patch.object(httpx.AsyncClient, 'post', post):
        result = await openrouter.query_model('test/model', [], stage='STAGE1')
    assert result['truncated'] is expected
    assert result['finish_reason'] == reason
    assert result['generation_id'] == 'generation-test'
    assert result['effective_max_tokens'] == 8192
    if expected:
        assert result['completion_status'] == 'truncated_empty'
        assert not result.get('error')


def test_stage_and_model_budgets(monkeypatch, tmp_path):
    from backend.generation import get_generation_limits
    monkeypatch.setattr(runtime_settings, 'SETTINGS_FILE', tmp_path / 'settings.json')
    settings = runtime_settings.RuntimeSettings(
        generation_limits={'stage1': {'max_tokens': 4096}},
        model_generation_limits={'test/model': {'stage1': {'max_tokens': 16384, 'reasoning_max_tokens': 4096}}})
    runtime_settings.save_runtime_settings(settings)
    assert get_generation_limits('other', 'STAGE1').max_tokens == 4096
    assert get_generation_limits('test/model', 'STAGE1').max_tokens == 16384
    assert get_generation_limits('test/model', 'STAGE3_FALLBACK').max_tokens == 8192


@pytest.mark.parametrize('budget', [
    {'max_tokens': 127}, {'max_tokens': 65537},
    {'max_tokens': 2048, 'reasoning_max_tokens': 2048},
    {'reasoning_max_tokens': 100},
    {'reasoning_effort': 'high', 'reasoning_max_tokens': 1024},
    {'reasoning_effort': 'invented'}, {'max_tokens': True},
])
def test_reject_invalid_budgets(budget):
    with pytest.raises(ValidationError):
        runtime_settings.RuntimeSettings(generation_limits={'stage1': budget})


@pytest.mark.asyncio
async def test_ollama_length_and_num_predict(monkeypatch):
    payloads = []
    async def post(self, url, **kwargs):
        payloads.append(kwargs['json'])
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'message': {'content': 'partial'}, 'done_reason': 'length', 'eval_count': 8192})
    with patch.object(httpx.AsyncClient, 'post', post):
        result = await ollama.query_model('test-model', [])
    assert payloads[0]['options']['num_predict'] == 8192
    assert result['truncated'] is True
    assert result['native_finish_reason'] == 'length'


@pytest.mark.asyncio
async def test_explicit_reasoning_payload_and_stage_context(monkeypatch, tmp_path):
    from backend.router_dispatch import query_model
    monkeypatch.setattr(runtime_settings, 'SETTINGS_FILE', tmp_path / 'settings.json')
    monkeypatch.setattr(openrouter.config, 'OPENROUTER_API_KEY', 'test-only')
    runtime_settings.save_runtime_settings(runtime_settings.RuntimeSettings(
        generation_limits={'continuation': {'max_tokens': 4096, 'reasoning_effort': 'low'},
                           'stage3': {'max_tokens': 16384}}))
    payloads = []
    async def post(self, url, **kwargs):
        payloads.append(kwargs['json'])
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': {'content': 'done'}, 'finish_reason': 'stop'}],
            'message': {'content': 'done'}, 'done_reason': 'stop'})
    with patch.object(httpx.AsyncClient, 'post', post):
        result = await query_model('openrouter', model='m', messages=[], stage='CONTINUATION')
        await query_model('ollama', model='m', messages=[], stage='STAGE3')
        unsupported = await query_model('ollama', model='m', messages=[], stage='CONTINUATION')
    assert payloads[0]['max_tokens'] == 4096
    assert payloads[0]['reasoning'] == {'effort': 'low'}
    assert payloads[0]['provider'] == {'require_parameters': True}
    assert result['effective_max_tokens'] == 4096
    assert payloads[1]['options']['num_predict'] == 16384
    assert unsupported['error_type'] == 'configuration'
    assert len(payloads) == 2


def test_generation_metadata_propagates_without_inventing_usage():
    from backend.council import _usage_fields
    result = {'content': '', 'truncated': True, 'finish_reason': 'length',
              'generation_id': 'gen-one', 'effective_max_tokens': 8192}
    fields = _usage_fields(result)
    assert fields == {key: value for key, value in result.items() if key != 'content'}


@pytest.mark.asyncio
async def test_stage2_reasoning_only_truncation_is_not_unrelated_empty_error(monkeypatch):
    from backend import council
    async def query(*args, **kwargs):
        return {'test/model': {'content': '', 'truncated': True, 'finish_reason': 'length',
                               'completion_status': 'truncated_empty'}}
    monkeypatch.setattr(council.router_dispatch, 'query_models_with_stage_timeout', query)
    result, _ = await council.stage2_collect_rankings('question', [{'model': 'a', 'response': 'answer'}],
                                                   models=['test/model'])
    assert result[0]['truncated'] is True
    assert result[0]['ranking'] == ''
    assert not result[0].get('error')


@pytest.mark.asyncio
async def test_chairman_fallback_truncated_empty_does_not_launch_another_paid_model(monkeypatch):
    from backend import council
    calls = []
    async def query(*args, **kwargs):
        calls.append(kwargs['model'])
        if len(calls) == 1:
            return {'error': True, 'error_type': 'timeout'}
        return {'content': '', 'truncated': True, 'finish_reason': 'length',
                'completion_status': 'truncated_empty'}
    monkeypatch.setattr(council.router_dispatch, 'query_model', query)
    result = await council.stage3_synthesize_final('question',
        [{'model': 'one', 'response': 'answer'}, {'model': 'two', 'response': 'answer2'}],
        [], chairman='chair')
    assert calls == ['chair', 'one']
    assert result['truncated'] is True
    assert result['response'] == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('reasoning,expected_temperature', [(None, 0.5), ('medium', None)])
async def test_strict_reasoning_routing_does_not_require_optional_temperature(monkeypatch, tmp_path, reasoning, expected_temperature):
    monkeypatch.setattr(runtime_settings, 'SETTINGS_FILE', tmp_path / 'settings.json')
    monkeypatch.setattr(openrouter.config, 'OPENROUTER_API_KEY', 'test-only')
    runtime_settings.save_runtime_settings(runtime_settings.RuntimeSettings(
        generation_limits={'stage1': {'max_tokens': 8192, 'reasoning_effort': reasoning}}))
    payloads = []
    async def post(self, url, **kwargs):
        payloads.append(kwargs['json'])
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': {'content': 'answer'}, 'finish_reason': 'stop'}]})
    with patch.object(httpx.AsyncClient, 'post', post):
        await openrouter.query_model('test/model', [], stage='STAGE1', temperature=0.5)
    assert payloads[0].get('temperature') == expected_temperature
    if reasoning:
        assert 'temperature' not in payloads[0]
        assert payloads[0]['provider'] == {'require_parameters': True}
