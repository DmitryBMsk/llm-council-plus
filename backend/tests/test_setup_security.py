"""Setup endpoint lockdown (B0.1).

The setup endpoint must refuse once the app is configured, on every deployment
shape — including Ollama / Docker-``environment:`` where no writable .env exists.
A durable marker in the data volume is the source of truth.

All tests isolate DATA_DIR and the .env path to tmp so the real repo files are
never read or written.
"""
from starlette.testclient import TestClient


def _isolate(tmp_path, monkeypatch):
    """Point setup at a tmp DATA_DIR and a tmp .env; return the setup module."""
    from .. import config
    from ..api.routes import setup as setup_mod

    data_dir = tmp_path / "conversations"
    env_file = tmp_path / ".env"
    env_file.write_text("")

    # Set via env too, so config.reload_config() keeps pointing at tmp.
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setattr(config, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(config, "ROUTER_TYPE", "ollama")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(setup_mod, "_env_path", lambda: env_file)
    return setup_mod


def test_is_setup_complete_false_when_unconfigured(tmp_path, monkeypatch):
    setup_mod = _isolate(tmp_path, monkeypatch)
    assert setup_mod._is_setup_complete() is False


def test_is_setup_complete_true_when_marker_present(tmp_path, monkeypatch):
    setup_mod = _isolate(tmp_path, monkeypatch)
    marker = setup_mod._setup_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("true\n")
    assert setup_mod._is_setup_complete() is True


def test_setup_endpoint_blocked_when_marker_exists(tmp_path, monkeypatch):
    setup_mod = _isolate(tmp_path, monkeypatch)
    marker = setup_mod._setup_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("true\n")

    from ..main import app
    client = TestClient(app)
    resp = client.post("/api/setup/config", json={"router_type": "ollama"})
    assert resp.status_code == 403


def test_startup_locks_wizard_on_ollama_deployment(tmp_path, monkeypatch):
    """Env-configured Ollama deployments never run the wizard — startup must
    write the marker so POST /api/setup/config cannot inject auth and take over."""
    setup_mod = _isolate(tmp_path, monkeypatch)
    assert setup_mod._is_setup_complete() is False

    setup_mod.mark_setup_complete_if_configured()

    assert setup_mod._setup_marker_path().exists()
    from ..main import app
    client = TestClient(app)
    resp = client.post("/api/setup/config", json={"auth_enabled": True})
    assert resp.status_code == 403


def test_startup_keeps_wizard_open_when_unconfigured(tmp_path, monkeypatch):
    """Fresh install (openrouter, no key): startup must NOT lock the wizard."""
    from .. import config
    setup_mod = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "ROUTER_TYPE", "openrouter")

    setup_mod.mark_setup_complete_if_configured()

    assert not setup_mod._setup_marker_path().exists()
    assert setup_mod._is_setup_complete() is False


def test_is_setup_complete_true_when_auth_enabled(tmp_path, monkeypatch):
    """Configured auth must lock the wizard even without a marker file."""
    from .. import config
    setup_mod = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    assert setup_mod._is_setup_complete() is True


def test_setup_writes_marker_then_blocks_second_attempt(tmp_path, monkeypatch):
    setup_mod = _isolate(tmp_path, monkeypatch)
    # Register the env keys the endpoint mutates so monkeypatch restores them.
    monkeypatch.setenv("ROUTER_TYPE", "ollama")
    monkeypatch.delenv("SETUP_COMPLETE", raising=False)

    from ..main import app
    client = TestClient(app)

    # First setup (Ollama, no key) succeeds and records the marker.
    r1 = client.post("/api/setup/config", json={"router_type": "ollama"})
    assert r1.status_code == 200, r1.text
    assert setup_mod._setup_marker_path().exists()

    # Second attempt is refused by the marker gate.
    r2 = client.post("/api/setup/config", json={"router_type": "ollama"})
    assert r2.status_code == 403
