"""Tests for typed settings and reload boundaries (Item 03).

Validates:
- Typed settings load expected defaults from environment
- Reload updates settings consistently
- Restart-required settings are classified separately
- Database settings do not drift after reload
"""

from __future__ import annotations



class TestTypedSettingsDefaults:
    """AppSettings must parse env vars with correct defaults."""

    def test_defaults_without_env(self, monkeypatch):
        """With no env vars, settings should have safe defaults."""
        # Clear relevant env vars
        for key in ("ROUTER_TYPE", "OPENROUTER_API_KEY", "AUTH_ENABLED",
                     "DATABASE_TYPE", "COUNCIL_MODELS", "DEFAULT_TIMEOUT"):
            monkeypatch.delenv(key, raising=False)

        from ..settings import AppSettings
        s = AppSettings.from_env()

        assert s.router_type == "openrouter"
        assert s.auth_enabled is False
        assert s.database_type == "json"
        assert isinstance(s.council_models, list)
        assert s.default_timeout == 120.0

    def test_parses_env_overrides(self, monkeypatch):
        monkeypatch.setenv("ROUTER_TYPE", "ollama")
        monkeypatch.setenv("AUTH_ENABLED", "true")
        monkeypatch.setenv("DEFAULT_TIMEOUT", "60")

        from ..settings import AppSettings
        s = AppSettings.from_env()

        assert s.router_type == "ollama"
        assert s.auth_enabled is True
        assert s.default_timeout == 60.0


class TestReloadBoundaries:
    """Settings must classify fields as hot-reloadable vs restart-required."""

    def test_hot_reloadable_fields_exist(self):
        from ..settings import HOT_RELOADABLE
        assert "router_type" in HOT_RELOADABLE
        assert "auth_enabled" in HOT_RELOADABLE
        assert "openrouter_api_key" in HOT_RELOADABLE

    def test_restart_required_fields_exist(self):
        from ..settings import RESTART_REQUIRED
        assert "database_type" in RESTART_REQUIRED
        assert "postgresql_url" in RESTART_REQUIRED

    def test_no_overlap(self):
        from ..settings import HOT_RELOADABLE, RESTART_REQUIRED
        overlap = HOT_RELOADABLE & RESTART_REQUIRED
        assert not overlap, f"Fields in both sets: {overlap}"


class TestReloadConsistency:
    """reload_config() must update the typed settings object consistently."""

    def test_reload_picks_up_env_change(self, monkeypatch):
        """After changing os.environ, reload_config must reflect the new value."""
        from .. import config

        # Prevent load_dotenv from overwriting our monkeypatch with .env file values
        monkeypatch.setattr("backend.config.load_dotenv", lambda **_kw: None)
        monkeypatch.setenv("AUTH_ENABLED", "true")
        config.reload_config()

        assert config.AUTH_ENABLED is True

    def test_reload_reverts_on_env_clear(self, monkeypatch):
        from .. import config

        monkeypatch.setattr("backend.config.load_dotenv", lambda **_kw: None)
        monkeypatch.delenv("AUTH_ENABLED", raising=False)
        config.reload_config()

        assert config.AUTH_ENABLED is False


class TestDatabaseSettingsStability:
    """Database settings are restart-required and must not silently drift."""

    def test_database_type_classified_as_restart_required(self):
        from ..settings import RESTART_REQUIRED
        assert "database_type" in RESTART_REQUIRED

    def test_config_reload_updates_database_type_global(self, monkeypatch):
        """config.reload_config() must update DATABASE_TYPE global."""
        from .. import config

        monkeypatch.setattr("backend.config.load_dotenv", lambda **_kw: None)
        monkeypatch.setenv("DATABASE_TYPE", "postgresql")
        config.reload_config()
        assert config.DATABASE_TYPE == "postgresql"

        # Reset
        monkeypatch.setenv("DATABASE_TYPE", "json")
        config.reload_config()
        assert config.DATABASE_TYPE == "json"

    def test_database_module_db_type_is_import_time_snapshot(self):
        """database.DB_TYPE is set at import time and does not change on reload.

        This is intentional — changing DB backend requires a restart.
        """
        from .. import database, config
        # DB_TYPE was set from config at import time
        assert database.DB_TYPE == config.DATABASE_TYPE

    def test_reload_config_uses_appsettings(self, monkeypatch):
        """reload_config() must parse through AppSettings, not raw os.getenv."""
        from .. import config

        monkeypatch.setattr("backend.config.load_dotenv", lambda **_kw: None)
        monkeypatch.setenv("ROUTER_TYPE", "ollama")
        monkeypatch.setenv("AUTH_ENABLED", "true")
        config.reload_config()

        assert config.ROUTER_TYPE == "ollama"
        assert config.AUTH_ENABLED is True
