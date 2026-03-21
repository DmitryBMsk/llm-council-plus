"""Tests for /api/models router_type query param."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_get_models_accepts_router_type_query_param_and_ollama_includes_context_length(monkeypatch):
    """
    GET /api/models?router_type=ollama should use the ollama path and include contextLength
    so the frontend can validate chairman context constraints.
    """
    from ..main import app

    # Force the endpoint to take the ollama path regardless of env
    monkeypatch.setattr("backend.main.OLLAMA_HOST", "localhost:11434", raising=False)

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"models": [{"name": "llama3.1:latest", "details": {"family": "llama"}}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("backend.main.httpx.AsyncClient", lambda *a, **k: FakeClient())

    client = TestClient(app)
    resp = client.get("/api/models?router_type=ollama")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["router_type"] == "ollama"
    assert payload["models"], "Expected at least one model"
    assert "contextLength" in payload["models"][0]

