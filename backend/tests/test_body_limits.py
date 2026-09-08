"""Request limits run before multipart spooling and ignore response size."""
import httpx
import pytest
from fastapi import FastAPI, File, UploadFile, Request
from starlette.responses import StreamingResponse
from starlette.testclient import TestClient
from backend.body_limits import RequestBodyLimitMiddleware


def make_app(limit=256):
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=limit)

    @app.post('/body')
    async def body(request: Request):
        return {'size': len(await request.body())}

    @app.post('/upload')
    async def upload(file: UploadFile = File(...)):
        return {'size': len(await file.read())}

    @app.post('/stream')
    async def stream(request: Request):
        await request.body()
        async def events():
            yield 'data: ' + 'x' * 1000 + '\n\n'
        return StreamingResponse(events(), media_type='text/event-stream')
    return app


def test_content_length_rejected_before_app_reads():
    async def must_not_run(scope, receive, send):
        pytest.fail('oversized Content-Length reached downstream app')
    client = TestClient(RequestBodyLimitMiddleware(must_not_run, max_bytes=4))
    response = client.post('/', content=b'12345')
    assert response.status_code == 413
    assert response.json()['detail'] == 'Request body exceeds 4 bytes'


def test_exact_boundary_and_large_sse_response_allowed():
    client = TestClient(make_app(4))
    assert client.post('/body', content=b'1234').json() == {'size': 4}
    response = client.post('/stream', content=b'1234')
    assert response.status_code == 200
    assert response.text.startswith('data: ')
    assert len(response.content) > 1000


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/body', '/upload'])
async def test_chunked_overflow_returns_413_even_when_multipart_parser_catches_error(path):
    boundary = 'test-boundary'
    async def chunks():
        if path == '/upload':
            yield (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n'
                   'Content-Type: text/plain\r\n\r\n').encode()
        yield b'x' * 150
        yield b'y' * 150
        pytest.fail('middleware read past the chunk which crossed its limit')
    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'} if path == '/upload' else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app()), base_url='http://test') as client:
        response = await client.post(path, content=chunks(), headers=headers)
    assert response.status_code == 413
    assert response.json()['detail'] == 'Request body exceeds 256 bytes'


def test_multipart_with_length_rejected_and_small_file_accepted():
    client = TestClient(make_app(256))
    assert client.post('/upload', files={'file': ('a.txt', b'x' * 500)}).status_code == 413
    assert client.post('/upload', files={'file': ('a.txt', b'hello')}).json() == {'size': 5}


def test_env_limit_must_be_positive_integer(monkeypatch):
    monkeypatch.setenv('MAX_REQUEST_BODY_BYTES', '4')
    client = TestClient(RequestBodyLimitMiddleware(make_app()))
    assert client.post('/body', content=b'12345').status_code == 413
    for invalid in ['0', '-1', 'not-a-number']:
        monkeypatch.setenv('MAX_REQUEST_BODY_BYTES', invalid)
        with pytest.raises(ValueError, match='MAX_REQUEST_BODY_BYTES'):
            RequestBodyLimitMiddleware(make_app())


@pytest.mark.asyncio
async def test_overflow_after_headers_does_not_send_second_response():
    messages = []
    async def application(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'data: started\n\n', 'more_body': True})
        await receive()
    async def receive():
        return {'type': 'http.request', 'body': b'12345', 'more_body': False}
    async def send(message):
        messages.append(message)
    await RequestBodyLimitMiddleware(application, max_bytes=4)({'type': 'http', 'headers': []}, receive, send)
    assert [message['type'] for message in messages].count('http.response.start') == 1
    assert messages[0]['status'] == 200
    assert messages[-1] == {'type': 'http.response.body', 'body': b'', 'more_body': False}
