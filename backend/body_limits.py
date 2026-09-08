"""Bound incoming ASGI bodies before JSON parsing or multipart spooling."""
import json
import logging
import os

logger = logging.getLogger(__name__)
DEFAULT_MAX_REQUEST_BODY_BYTES = 40 * 1024 * 1024
MAX_CONFIGURED_REQUEST_BODY_BYTES = 1024 * 1024 * 1024


class RequestBodyTooLarge(Exception):
    """Internal receive signal; never leak a parser's replacement 400/500."""


class RequestBodyLimitMiddleware:
    def __init__(self, app, max_bytes=None):
        self.app = app
        configured = max_bytes if max_bytes is not None else os.getenv(
            'MAX_REQUEST_BODY_BYTES', str(DEFAULT_MAX_REQUEST_BODY_BYTES))
        try:
            self.max_bytes = int(configured)
        except (TypeError, ValueError) as exc:
            raise ValueError('MAX_REQUEST_BODY_BYTES must be a positive integer') from exc
        if isinstance(configured, bool) or not 0 < self.max_bytes <= MAX_CONFIGURED_REQUEST_BODY_BYTES:
            raise ValueError('MAX_REQUEST_BODY_BYTES must be between 1 and 1073741824 bytes')

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        overflow = False
        started = False
        completed = False
        consumed = 0
        payload = json.dumps({'detail': f'Request body exceeds {self.max_bytes} bytes'}).encode()

        async def reject():
            nonlocal started, completed
            if completed:
                return
            if not started:
                await send({'type': 'http.response.start', 'status': 413, 'headers': [
                    (b'content-type', b'application/json'),
                    (b'content-length', str(len(payload)).encode()),
                ]})
                started = True
                await send({'type': 'http.response.body', 'body': payload})
            else:
                # HTTP status cannot change once sent. End the existing stream
                # cleanly; never emit a second set of response headers/body JSON.
                logger.warning('Request limit exceeded after response headers were sent')
                await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
            completed = True

        for name, value in scope.get('headers', []):
            if name.lower() == b'content-length':
                try:
                    declared = int(value)
                except ValueError:
                    continue  # Actual received bytes remain authoritative.
                if declared > self.max_bytes:
                    await reject()
                    return

        async def limited_receive():
            nonlocal consumed, overflow
            if overflow:
                raise RequestBodyTooLarge()
            message = await receive()
            if message['type'] == 'http.request':
                consumed += len(message.get('body', b''))
                if consumed > self.max_bytes:
                    overflow = True
                    raise RequestBodyTooLarge()
            return message

        async def limited_send(message):
            nonlocal started, completed
            if overflow:
                # Multipart parsers may catch the receive exception and send a
                # 400. Replace it before any response headers leave middleware.
                await reject()
                return
            if message['type'] == 'http.response.start':
                started = True
            elif message['type'] == 'http.response.body' and not message.get('more_body', False):
                completed = True
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except RequestBodyTooLarge:
            await reject()
