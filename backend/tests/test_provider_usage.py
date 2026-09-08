"""Real HTTP response parsing keeps provider token/cost accounting."""
import httpx
import pytest

from backend import config, ollama, openrouter


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,data,usage", [
    (openrouter, {"choices": [{"message": {"content": "answer"}}], "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7, "cost": 0.012}}, {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7, "cost": 0.012}),
    (ollama, {"message": {"content": "answer"}, "prompt_eval_count": 4, "eval_count": 3}, {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}),
    (ollama, {"message": {"content": "answer"}, "prompt_eval_count": 0, "eval_count": 0}, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
])
async def test_provider_usage_is_retained(monkeypatch, provider, data, usage):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-only")
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data)), **kwargs))
    result = await provider.query_model("model", [{"role": "user", "content": "hello"}])
    assert result["usage"] == usage
    assert result["content"] == "answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,data", [
    (openrouter, {"choices": [{"message": {"content": "answer"}}]}),
    (ollama, {"message": {"content": "answer"}}),
])
async def test_missing_usage_does_not_invent_zero_cost(monkeypatch, provider, data):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-only")
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data)), **kwargs))
    assert await provider.query_model("model", []) == {"content": "answer", "reasoning_details": None}
