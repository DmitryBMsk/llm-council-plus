"""File-upload size limits (B0.3).

Non-image files (PDF/text/markdown) must be size-checked BEFORE parsing so a
small-on-disk file cannot exhaust memory during parsing (PDF bomb).
"""
import asyncio
import threading

import pytest
from fastapi import HTTPException, UploadFile
from starlette.testclient import TestClient


MAX_UPLOAD_SIZE = 20 * 1024 * 1024
MAX_FILE_SIZE = 10 * 1024 * 1024


class RecordingUploadStream:
    """File-like stream that records the byte bound used by UploadFile."""

    def __init__(self, payload: bytes, *, barrier: threading.Barrier | None = None):
        self._payload = payload
        self._barrier = barrier
        self._rolled = barrier is not None
        self.read_sizes = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self._barrier is not None:
            self._barrier.wait(timeout=5)
        if size < 0:
            return self._payload
        return self._payload[:size]


def make_upload(
    filename: str,
    payload: bytes,
    *,
    barrier: threading.Barrier | None = None,
) -> tuple[UploadFile, RecordingUploadStream]:
    stream = RecordingUploadStream(payload, barrier=barrier)
    return UploadFile(file=stream, filename=filename), stream


@pytest.fixture()
def client(monkeypatch):
    from .. import config
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    from ..main import app
    return TestClient(app)


def test_oversized_text_upload_rejected_before_parse(client):
    big = b"a" * (MAX_FILE_SIZE + 1)
    resp = client.post("/api/upload", files={"file": ("big.txt", big, "text/plain")})
    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"].lower()


def test_small_text_upload_ok(client):
    resp = client.post("/api/upload", files={"file": ("note.txt", b"hello world", "text/plain")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "hello world"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "max_size", "expected_detail"),
    [
        ("oversized.txt", MAX_FILE_SIZE, "File too large. Maximum size is 10MB."),
        ("oversized.png", MAX_UPLOAD_SIZE, "Image file too large. Maximum size is 20MB."),
    ],
)
async def test_oversized_upload_uses_bounded_read_and_skips_parse(
    monkeypatch,
    filename,
    max_size,
    expected_detail,
):
    from backend.api.routes import conversations

    def parse_must_not_run(*_args, **_kwargs):
        pytest.fail("parse_file must not run for an oversized upload")

    monkeypatch.setattr(conversations, "parse_file", parse_must_not_run)
    upload, stream = make_upload(filename, b"x" * (max_size + 1))

    with pytest.raises(HTTPException) as exc_info:
        await conversations.upload_file(upload, current_user="guest")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == expected_detail
    assert stream.read_sizes == [max_size + 1]


@pytest.mark.asyncio
async def test_concurrent_oversized_uploads_are_independently_bounded(monkeypatch):
    from backend.api.routes import conversations

    def parse_must_not_run(*_args, **_kwargs):
        pytest.fail("parse_file must not run for an oversized upload")

    monkeypatch.setattr(conversations, "parse_file", parse_must_not_run)
    upload_cases = [
        ("one.txt", MAX_FILE_SIZE),
        ("two.png", MAX_UPLOAD_SIZE),
        ("three.pdf", MAX_FILE_SIZE),
        ("four.md", MAX_FILE_SIZE),
    ]
    barrier = threading.Barrier(len(upload_cases))
    uploads_and_streams = [
        make_upload(filename, b"x" * (max_size + 1), barrier=barrier)
        for filename, max_size in upload_cases
    ]

    results = await asyncio.gather(
        *(
            conversations.upload_file(upload, current_user="guest")
            for upload, _stream in uploads_and_streams
        ),
        return_exceptions=True,
    )

    assert all(isinstance(result, HTTPException) for result in results)
    assert [result.status_code for result in results] == [400] * len(upload_cases)
    assert [stream.read_sizes for _upload, stream in uploads_and_streams] == [
        [max_size + 1]
        for _filename, max_size in upload_cases
    ]


@pytest.mark.asyncio
async def test_exact_limit_upload_remains_accepted(monkeypatch):
    from backend.api.routes import conversations

    payload = b"x" * MAX_FILE_SIZE
    upload, stream = make_upload("exact.txt", payload)
    parser_calls = []

    def fake_parse_file(filename, file_content):
        parser_calls.append((filename, file_content))
        return "parsed", "txt"

    monkeypatch.setattr(conversations, "parse_file", fake_parse_file)

    response = await conversations.upload_file(upload, current_user="guest")

    assert stream.read_sizes == [MAX_FILE_SIZE + 1]
    assert parser_calls == [("exact.txt", payload)]
    assert response == {
        "filename": "exact.txt",
        "file_type": "txt",
        "content": "parsed",
        "char_count": 6,
    }
