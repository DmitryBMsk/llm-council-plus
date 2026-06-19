"""File-upload size limits (B0.3).

Non-image files (PDF/text/markdown) must be size-checked BEFORE parsing so a
small-on-disk file cannot exhaust memory during parsing (PDF bomb).
"""
import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    from .. import config
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    from ..main import app
    return TestClient(app)


def test_oversized_text_upload_rejected_before_parse(client):
    big = b"a" * (21 * 1024 * 1024)  # 21MB > 20MB cap
    resp = client.post("/api/upload", files={"file": ("big.txt", big, "text/plain")})
    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"].lower()


def test_small_text_upload_ok(client):
    resp = client.post("/api/upload", files={"file": ("note.txt", b"hello world", "text/plain")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "hello world"
