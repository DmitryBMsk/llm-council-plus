"""httpx's own request log must not carry credentials from provider URLs (#76)."""

import asyncio
import logging

import httpx

import backend.main  # noqa: F401  (applies the app's logging setup)
from backend import config, ollama


def test_successful_ollama_call_keeps_proxy_credentials_out_of_the_log(monkeypatch, caplog):
    monkeypatch.setattr(config, "OLLAMA_HOST", "PROXY_USER:PROXY_SECRET@ollama.test:11434", raising=False)
    dialed = []

    def reply(request):
        dialed.append(request.url.host)
        return httpx.Response(200, json={"message": {"content": "hello"}, "done_reason": "stop"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        ollama.httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(reply), **kwargs),
    )

    with caplog.at_level(logging.INFO):
        result = asyncio.run(ollama.query_model("a/alpha", [{"role": "user", "content": "hi"}]))
        logging.getLogger("httpx").warning("HTTPX_WARNING_9")

    assert result["content"] == "hello" and dialed == ["ollama.test"]
    assert "PROXY_USER" not in caplog.text and "PROXY_SECRET" not in caplog.text
    assert "HTTPX_WARNING_9" in caplog.text  # httpx warnings still reach the log
