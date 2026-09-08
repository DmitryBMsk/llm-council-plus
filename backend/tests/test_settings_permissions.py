"""Global settings permissions exercised through real signed JWT authentication."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import auth, config, runtime_settings
from backend.api.routes.settings import router


@pytest.fixture
def settings_client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "JWT_SECRET", "isolated-test-secret-at-least-32-bytes-long")
    monkeypatch.setattr(auth, "USERS", {name: {} for name in ("admin", "bob", "alice")})
    monkeypatch.setenv("AUTH_ADMIN_USERS", "admin")
    monkeypatch.setattr(runtime_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


def headers(name):
    return {"Authorization": f"Bearer {auth.create_token(name)[0]}"}


@pytest.mark.parametrize("method,path,payload", [
    ("patch", "/api/settings", {"stage1_prompt_template": "bob override"}),
    ("post", "/api/settings/import", {"stage1_prompt_template": "bob override"}),
    ("post", "/api/settings/reset", {}),
])
def test_ordinary_user_cannot_mutate_global_settings(settings_client, method, path, payload):
    before = settings_client.get("/api/settings", headers=headers("alice")).json()
    response = getattr(settings_client, method)(path, json=payload, headers=headers("bob"))
    assert response.status_code == 403
    assert "administrator" in response.json()["detail"]
    assert settings_client.get("/api/settings", headers=headers("alice")).json() == before


def test_admin_allowlist_defaults_to_empty(settings_client, monkeypatch):
    monkeypatch.delenv("AUTH_ADMIN_USERS")
    response = settings_client.patch("/api/settings", json={"council_temperature": 1}, headers=headers("admin"))
    assert response.status_code == 403


def test_read_permissions_and_local_mode(settings_client, monkeypatch):
    assert settings_client.get("/api/settings", headers=headers("bob")).json()["can_edit"] is False
    assert settings_client.get("/api/settings", headers=headers("admin")).json()["can_edit"] is True
    assert settings_client.patch("/api/settings", json={}).status_code == 401
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    assert settings_client.get("/api/settings").json()["can_edit"] is True
    assert settings_client.patch("/api/settings", json={"council_temperature": 1}).status_code == 200


def test_admin_mutations_have_durable_audit_without_values(settings_client):
    for method, path, data in [
        ("patch", "/api/settings", {"stage1_prompt_template": "private prompt"}),
        ("post", "/api/settings/import", {"stage2_temperature": 0.9, "API_KEY": "secret"}),
        ("post", "/api/settings/reset", {}),
    ]:
        assert getattr(settings_client, method)(path, json=data, headers=headers("admin")).status_code == 200
    raw = json.loads(runtime_settings.SETTINGS_FILE.read_text())
    assert [entry["version"] for entry in raw["_audit"]] == [1, 2, 3]
    assert [entry["action"] for entry in raw["_audit"]] == ["patch", "import", "reset"]
    assert all(entry["actor"] == "admin" for entry in raw["_audit"])
    assert "private prompt" not in json.dumps(raw["_audit"])
    assert "secret" not in json.dumps(raw)
    assert "_audit" not in settings_client.get("/api/settings/export", headers=headers("bob")).json()


@pytest.mark.parametrize("payload", [
    {"web_search_provider": "unknown"},
    {"stage1_prompt_template": "x" * 200_001},
    {"council_temperature": 3},
])
def test_import_has_same_validation_as_patch(settings_client, payload):
    for method, path in [("patch", "/api/settings"), ("post", "/api/settings/import")]:
        assert getattr(settings_client, method)(path, json=payload, headers=headers("admin")).status_code == 422
