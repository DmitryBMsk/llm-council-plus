"""Live HTTP + real SQL + local HTTP LLM contract (SQL_TEST_URL opts in)."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest


@pytest.mark.skipif(not os.getenv("SQL_TEST_URL"), reason="requires dedicated SQL server")
def test_live_sql_conversation_roundtrip(tmp_path):
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps({"message": {"content": "SQL_E2E_OK"}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = os.environ["SQL_TEST_URL"]
    kind = "mysql" if url.startswith("mysql") else "postgresql"
    env = {
        **os.environ,
        "PYTHON_DOTENV_DISABLED": "1",
        "AUTH_ENABLED": "false",
        "AUTH_USERS": "{}",
        "DATABASE_TYPE": kind,
        "MYSQL_URL": url,
        "POSTGRESQL_URL": url,
        "DATA_DIR": str(tmp_path),
        "RUNTIME_SETTINGS_FILE": str(tmp_path / "settings.json"),
        "ROUTER_TYPE": "ollama",
        "OLLAMA_HOST": f"127.0.0.1:{provider.server_port}",
        "COUNCIL_MODELS": "e2e-a,e2e-b",
        "CHAIRMAN_MODEL": "e2e-a",
        "ENABLE_MEMORY": "false",
        "ENABLE_EXA": "false",
        "ENABLE_TAVILY": "false",
        "ENABLE_BRAVE": "false",
        "RUN_CONTROL_DB": str(tmp_path / "runs.db"),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    cid = None
    try:
        for _ in range(100):
            try:
                if httpx.get(base, timeout=0.2).is_success:
                    break
            except httpx.HTTPError:
                pass
            assert proc.poll() is None
            time.sleep(0.05)
        with httpx.Client(base_url=base, timeout=20) as client:
            response = client.post("/api/conversations", json={"router_type": "ollama", "models": ["e2e-a", "e2e-b"]})
            assert response.status_code == 200
            cid = response.json()["id"]
            result = client.post(f"/api/conversations/{cid}/message", json={"content": "Hello"})
            assert result.status_code == 200
            assert len(result.json()["stage1"]) == 2
            with ThreadPoolExecutor(max_workers=2) as pool:
                requests = list(
                    pool.map(
                        lambda i: client.patch(f"/api/conversations/{cid}/title", json={"title": f"title-{i}"}),
                        range(2),
                    )
                )
            assert all(r.status_code == 200 for r in requests)
            saved = client.get(f"/api/conversations/{cid}").json()
            assert len(saved["messages"]) == 2
            assert saved["title"] in ["title-0", "title-1"]
    finally:
        if cid:
            httpx.delete(f"{base}/api/conversations/{cid}", timeout=5)
        proc.terminate()
        proc.wait(timeout=5)
        provider.shutdown()
        provider.server_close()
