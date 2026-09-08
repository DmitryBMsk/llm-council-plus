"""Tavily boundary regressions; HTTP is replaced, search logic is real."""
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from backend import council, tools


def test_tavily_long_query_is_bounded_and_sources_survive(monkeypatch):
    seen = []
    def post(url, **kwargs):
        seen.append(kwargs)
        return httpx.Response(200, json={'results': [{'title': 'Source', 'url': 'https://example.com', 'content': 'Evidence'}], 'request_id': 'req-ok'})
    monkeypatch.setattr(httpx, 'post', post)
    result = tools.tavily_tool('test-secret').invoke('latest research ' * 700)
    assert len(seen) == 1
    assert 0 < len(seen[0]['json']['query']) <= 1200
    assert seen[0]['timeout'] is not None
    assert result['status'] == 'success'
    assert result['results'][0]['url'] == 'https://example.com'


@pytest.mark.parametrize('status', [400, 401, 429, 500])
def test_http_error_is_structured_and_secret_safe(monkeypatch, status):
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: httpx.Response(status, json={'detail': {'error': 'bad test-secret'}, 'request_id': 'req-fail'}))
    result = tools.tavily_tool('test-secret').invoke('latest research')
    assert result['status'] == 'error'
    assert result['error']['status_code'] == status
    assert 'test-secret' not in json.dumps(result)
    assert result['request_id'] == 'req-fail'


def test_timeout_is_not_evidence(monkeypatch):
    def timeout(*a, **kw):
        raise httpx.ReadTimeout('secret request details')
    monkeypatch.setattr(httpx, 'post', timeout)
    result = tools.tavily_tool('test-secret').invoke('latest research')
    assert result['status'] == 'error'
    assert result['error']['code'] == 'timeout'
    assert 'secret request details' not in str(result)


@pytest.mark.parametrize('direct', [True, False])
def test_failure_stays_failure_in_council(monkeypatch, direct):
    from types import SimpleNamespace
    failure = {'status': 'error', 'error': {'code': 'http_error', 'status_code': 400, 'message': 'Bad query'}}
    monkeypatch.setattr(council, 'get_available_tools', lambda: [SimpleNamespace(name='tavily_search', invoke=lambda q: failure)])
    output = council.run_tavily_direct('latest research', 'tavily') if direct else council.run_tools_for_query('latest research')
    assert output[0]['status'] == 'error'
    assert not output[0]['result']


@pytest.mark.asyncio
@pytest.mark.parametrize('answer', [None, {'content': 'word ' * 500}, {'content': '   '}])
async def test_optimizer_fallback_and_output_are_bounded(monkeypatch, answer):
    monkeypatch.setattr(council.router_dispatch, 'query_model', AsyncMock(return_value=answer))
    result = await council.optimize_search_query('latest research ' * 700)
    assert 0 < len(result) <= 1200


def test_legacy_error_excluded_from_evidence():
    from backend.search_results import tool_context
    text = tool_context([{'tool': 'tavily_search', 'result': json.dumps("HTTPError('400 Bad Request')")}])
    assert 'HTTPError' not in text
    assert 'Search unavailable' in text
    assert 'Search Results:' not in text


@pytest.mark.asyncio
async def test_long_automatic_search_uses_optimized_query_without_changing_question(monkeypatch):
    from types import SimpleNamespace
    seen = []
    original = 'latest research ' * 700
    monkeypatch.setattr(council.router_dispatch, 'query_model', AsyncMock(return_value={'content': 'specific research topic'}))
    monkeypatch.setattr(council, 'get_available_tools', lambda: [SimpleNamespace(name='tavily_search', invoke=lambda q: seen.append(q) or [{'title': 'ok'}])])
    await council.collect_auto_tools(original)
    assert seen == ['specific research topic']
    assert council.build_context_prompt([], original) == original


@pytest.mark.parametrize('body, expected', [({'results': []}, 'empty'), ({}, 'error'), ([], 'error')])
def test_empty_and_malformed_responses(monkeypatch, body, expected):
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: httpx.Response(200, json=body))
    assert tools.tavily_tool('test-secret').invoke('latest research')['status'] == expected
