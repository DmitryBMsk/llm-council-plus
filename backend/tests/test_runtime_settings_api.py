"""Tests for runtime settings API endpoints."""

from __future__ import annotations

from pathlib import Path


def test_runtime_settings_endpoints_roundtrip(tmp_path, monkeypatch):
    # Import app after patching settings file location.
    from .. import runtime_settings as rs

    monkeypatch.setattr(rs, "SETTINGS_FILE", Path(tmp_path) / "runtime_settings.json")

    from fastapi.testclient import TestClient
    from ..main import app

    client = TestClient(app)

    # Defaults
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["council_temperature"] == 0.5
    assert "stage1_prompt_template" in data

    # Patch update
    resp = client.patch("/api/settings", json={"council_temperature": 0.9})
    assert resp.status_code == 200
    assert resp.json()["council_temperature"] == 0.9

    # Export should include updated value
    resp = client.get("/api/settings/export")
    assert resp.status_code == 200
    assert resp.json()["council_temperature"] == 0.9

    # Reset should restore defaults
    resp = client.post("/api/settings/reset")
    assert resp.status_code == 200
    assert resp.json()["council_temperature"] == 0.5

    # Import should apply config (no secrets)
    import_payload = {
        "council_temperature": 0.66,
        "stage2_temperature": 0.22,
        "chairman_temperature": 0.33,
        "stage1_prompt_template": "{full_query}",
        "stage2_prompt_template": "Question: {user_query}\n\n{responses_text}",
        "stage3_prompt_template": "Q: {user_query}\n\n{stage1_text}\n\n{rankings_block}",
        # Should be ignored by the import endpoint.
        "OPENROUTER_API_KEY": "should-not-be-accepted",
    }
    resp = client.post("/api/settings/import", json=import_payload)
    assert resp.status_code == 200
    assert resp.json()["council_temperature"] == 0.66
