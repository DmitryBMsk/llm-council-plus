"""Socket HTTP E2E: real login/JWT, settings routes and isolated persisted data."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx


def test_live_settings_roles_and_audit(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": str(root),
        "PYTHON_DOTENV_DISABLED": "1",
        "AUTH_ENABLED": "true",
        "AUTH_USERS": json.dumps({name: "e2e-password" for name in ("admin", "bob", "alice")}),
        "AUTH_ADMIN_USERS": "admin",
        "JWT_SECRET": "isolated-e2e-signing-key-at-least-32-bytes",
        "RUNTIME_SETTINGS_FILE": str(tmp_path / "settings.json"),
    }
    code = '''
import sys
import uvicorn
from fastapi import FastAPI
from backend.api.routes.settings import router as settings
from backend.api.routes.auth_routes import router as auth
app = FastAPI()
app.include_router(settings)
app.include_router(auth)
uvicorn.run(app, fd=int(sys.argv[1]), log_level="error")
'''
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        with (tmp_path / "server.log").open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-c", code, str(listener.fileno())],
                env=env, cwd=tmp_path, pass_fds=(listener.fileno(),), stdout=log, stderr=log,
            )
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1) as client:
                    for _ in range(100):
                        try:
                            if client.get("/api/auth/status").status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        assert process.poll() is None, (tmp_path / "server.log").read_text()
                        time.sleep(0.05)
                    else:
                        raise AssertionError("Server did not start")
                    tokens = {}
                    for name in ("admin", "bob", "alice"):
                        response = client.post("/api/auth", json={"username": name, "password": "e2e-password"})
                        assert response.status_code == 200
                        tokens[name] = {"Authorization": f"Bearer {response.json()['token']}"}
                    for name in ("bob", "alice"):
                        assert client.get("/api/settings", headers=tokens[name]).json()["can_edit"] is False
                        for method, path, data in [
                            ("PATCH", "/api/settings", {"stage1_prompt_template": "unauthorized"}),
                            ("POST", "/api/settings/import", {"stage1_prompt_template": "unauthorized"}),
                            ("POST", "/api/settings/reset", {}),
                        ]:
                            assert client.request(method, path, json=data, headers=tokens[name]).status_code == 403
                    assert client.patch("/api/settings", json={}).status_code == 401
                    assert client.patch("/api/settings", json={"stage1_prompt_template": "admin change"}, headers=tokens["admin"]).status_code == 200
                    assert client.get("/api/settings", headers=tokens["alice"]).json()["stage1_prompt_template"] == "admin change"
                    assert client.post("/api/settings/import", json={"web_search_provider": "invalid"}, headers=tokens["admin"]).status_code == 422
                    assert client.post("/api/settings/import", json={"stage2_temperature": 0.9}, headers=tokens["admin"]).status_code == 200
                    assert client.post("/api/settings/reset", json={}, headers=tokens["admin"]).status_code == 200
                    audit = json.loads((tmp_path / "settings.json").read_text())["_audit"]
                    assert [(row["actor"], row["version"]) for row in audit] == [("admin", 1), ("admin", 2), ("admin", 3)]
                    assert "admin change" not in json.dumps(audit)
            finally:
                process.terminate()
                process.wait(timeout=10)
