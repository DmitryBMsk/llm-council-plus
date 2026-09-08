import asyncio
import time
from unittest.mock import patch

import pytest
from backend.api.routes import conversations


@pytest.mark.asyncio
async def test_slow_storage_does_not_block_unrelated_coroutine():
    started = time.monotonic()

    def slow_get(*args, **kwargs):
        time.sleep(0.2)
        return {"id": "x", "messages": []}

    async def timer():
        await asyncio.sleep(0.01)
        return time.monotonic() - started

    with patch.object(conversations.storage, "get_conversation", slow_get):
        _, delay = await asyncio.gather(conversations.get_conversation("x", current_user="guest"), timer())
    assert delay < 0.1


def test_http_health_while_conversation_file_is_locked(tmp_path):
    """A blocked real storage request must not block another HTTP request."""
    import os
    import socket
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor
    import httpx
    from backend.storage import file_lock

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "PYTHON_DOTENV_DISABLED": "1",
        "AUTH_ENABLED": "false",
        "AUTH_USERS": "{}",
        "DATABASE_TYPE": "json",
        "DATA_DIR": str(tmp_path),
        "ENABLE_MEMORY": "false",
        "ROUTER_TYPE": "ollama",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(base, timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert proc.poll() is None
            time.sleep(0.05)
        with httpx.Client(base_url=base, timeout=3) as client, ThreadPoolExecutor(max_workers=1) as pool:
            cid = client.post("/api/conversations", json={}).json()["id"]
            with (tmp_path / f"{cid}.json.lock").open("a+b") as lock:
                with file_lock(lock):
                    pending = pool.submit(client.get, f"/api/conversations/{cid}")
                    time.sleep(0.1)
                    assert not pending.done()
                    assert client.get("/", timeout=0.5).status_code == 200
            assert pending.result(timeout=3).status_code == 200
    finally:
        proc.terminate()
        proc.wait(timeout=5)
