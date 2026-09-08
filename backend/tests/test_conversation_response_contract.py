"""HTTP contract tests for full-conversation responses."""

from starlette.testclient import TestClient


def test_create_and_get_round_trip_conversation_settings(tmp_path, monkeypatch):
    """Create/get responses must expose persisted router and prompt settings."""
    from backend import config, storage
    from backend.main import app

    monkeypatch.setattr(storage, "is_using_database", lambda: False)
    monkeypatch.setattr(storage.config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUTH_ENABLED", False)

    client = TestClient(app)
    created_response = client.post(
        "/api/conversations",
        json={
            "models": ["local-model"],
            "router_type": "ollama",
            "system_prompt": "Use the supplied evidence only",
        },
    )
    assert created_response.status_code == 200

    created = created_response.json()
    fetched_response = client.get(f"/api/conversations/{created['id']}")
    assert fetched_response.status_code == 200
    fetched = fetched_response.json()

    assert {
        "created": {
            "router_type": created.get("router_type"),
            "system_prompt": created.get("system_prompt"),
        },
        "fetched": {
            "router_type": fetched.get("router_type"),
            "system_prompt": fetched.get("system_prompt"),
        },
    } == {
        "created": {
            "router_type": "ollama",
            "system_prompt": "Use the supplied evidence only",
        },
        "fetched": {
            "router_type": "ollama",
            "system_prompt": "Use the supplied evidence only",
        },
    }
