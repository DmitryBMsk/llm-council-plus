"""Keenable web search provider; HTTP is replaced, formatting logic is real."""
import json

import httpx
import pytest

from backend import config, web_search

_RealAsyncClient = httpx.AsyncClient


def _mock_http(monkeypatch, handler):
    seen = []

    def recording(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        web_search.httpx,
        "AsyncClient",
        lambda **kw: _RealAsyncClient(transport=httpx.MockTransport(recording), **kw),
    )
    return seen


@pytest.fixture
def keenable_on(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_KEENABLE", True)
    monkeypatch.setattr(config, "KEENABLE_API_KEY", " kn-test-key ")


@pytest.mark.asyncio
async def test_keenable_request_and_formatting(monkeypatch, keenable_on):
    seen = _mock_http(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            json={
                "results": [
                    {"title": "A", "url": "https://a.example", "description": "Desc A", "snippet": "long A"},
                    {"title": "B", "url": "https://b.example", "description": "", "snippet": "Snippet B"},
                    {"title": "no url", "description": "dropped"},
                ]
            },
        ),
    )
    out = await web_search.perform_web_search("asyncio timeout", provider="keenable", max_results=80)

    assert len(seen) == 1
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == "https://api.keenable.ai/v1/search"
    assert req.headers["X-API-Key"] == "kn-test-key"
    assert "X-Keenable-Title" not in req.headers
    assert json.loads(req.content) == {"query": "asyncio timeout", "max_results": 50, "disable_cards": True}
    assert "Result 1:\nTitle: A\nURL: https://a.example\nSummary: Desc A" in out
    assert "Result 2:\nTitle: B\nURL: https://b.example\nSummary: Snippet B" in out
    assert "no url" not in out


@pytest.mark.asyncio
async def test_keenable_not_configured_makes_no_request(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_KEENABLE", False)
    monkeypatch.setattr(config, "KEENABLE_API_KEY", "kn-test-key")
    seen = _mock_http(monkeypatch, lambda r: httpx.Response(500))
    out = await web_search.perform_web_search("q", provider="keenable")
    assert seen == []
    assert "Keenable search is not configured" in out


@pytest.mark.asyncio
async def test_keenable_http_error_does_not_leak_key(monkeypatch, keenable_on):
    _mock_http(monkeypatch, lambda r: httpx.Response(401, json={"error": "invalid kn-test-key"}))
    out = await web_search.perform_web_search("q", provider="keenable")
    assert out == "[System Note: Keenable search failed. Please check your API key.]"
    assert "kn-test-key" not in out


@pytest.mark.asyncio
async def test_keenable_full_content_uses_jina_for_top_results(monkeypatch, keenable_on):
    _mock_http(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            json={"results": [
                {"title": "A", "url": "https://a.example", "snippet": "s"},
                {"title": "B", "url": "https://b.example", "snippet": "s"},
            ]},
        ),
    )
    fetched = []

    async def fake_jina(url, timeout=25.0):
        fetched.append(url)
        return "x" * 600

    monkeypatch.setattr(web_search, "_fetch_with_jina", fake_jina)
    out = await web_search.perform_web_search("q", provider="keenable", full_content_results=1)
    assert fetched == ["https://a.example"]
    assert "Content:\n" + "x" * 600 in out
    assert "Result 2:\nTitle: B\nURL: https://b.example\nSummary: s" in out
