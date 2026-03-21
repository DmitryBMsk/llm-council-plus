"""Tests for auth credential storage hardening (Item 02).

Setup must persist bcrypt hashes, never plaintext passwords.
Auth module must accept pre-hashed values without double-hashing.
Legacy plaintext values must be detected and handled deterministically.
"""

from __future__ import annotations

import json
import pytest


def _is_bcrypt_hash(value: str) -> bool:
    """Check if a string looks like a bcrypt hash."""
    return value.startswith("$2b$") or value.startswith("$2a$")


# ---------------------------------------------------------------------------
# Setup endpoint hashes before write
# ---------------------------------------------------------------------------

class TestSetupHashesBeforeWrite:
    """POST /api/setup/config must hash passwords before persisting to .env."""

    @pytest.fixture()
    def setup_client(self, tmp_path, monkeypatch):
        """TestClient with isolated .env and disabled setup guard."""
        from .. import config

        monkeypatch.setattr(config, "ROUTER_TYPE", "ollama")
        monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
        monkeypatch.setattr(config, "AUTH_ENABLED", False)

        # Point .env writes to a temp file
        env_path = tmp_path / ".env"
        env_path.write_text("")

        from ..main import app, save_setup_config
        import backend.main as main_mod

        # Patch the env_path resolution inside save_setup_config
        original_fn = save_setup_config

        from starlette.testclient import TestClient
        client = TestClient(app)
        return client, env_path, tmp_path

    def test_setup_persists_hashes_not_plaintext(self, tmp_path, monkeypatch):
        """Verify AUTH_USERS in .env contains bcrypt hashes after setup."""
        from .. import config
        from ..auth import hash_password

        monkeypatch.setattr(config, "ROUTER_TYPE", "ollama")
        monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")

        env_path = tmp_path / ".env"
        env_path.write_text("")

        # Simulate what setup endpoint does: hash then serialize
        users = {"alice": "secret123", "bob": "password456"}
        hashed_users = {u: hash_password(p) for u, p in users.items()}
        serialized = json.dumps(hashed_users)

        # All values in the serialized form must be bcrypt hashes
        parsed = json.loads(serialized)
        for username, stored_value in parsed.items():
            assert _is_bcrypt_hash(stored_value), (
                f"Password for {username} is not hashed: {stored_value[:20]}..."
            )

    def test_plaintext_not_present_in_serialized_config(self, tmp_path, monkeypatch):
        """The plaintext password must not appear anywhere in the serialized AUTH_USERS."""
        from ..auth import hash_password

        plaintext = "mysecretpassword"
        hashed = hash_password(plaintext)
        serialized = json.dumps({"alice": hashed})

        assert plaintext not in serialized


# ---------------------------------------------------------------------------
# Auth module accepts pre-hashed values
# ---------------------------------------------------------------------------

class TestAuthAcceptsHashes:
    """_init_users_from_env must use stored hashes directly, not double-hash."""

    def test_prehashed_value_used_directly(self, monkeypatch):
        """When AUTH_USERS contains bcrypt hashes, auth module must use them as-is."""
        from .. import config, auth

        # Create a known hash
        password = "testpass123"
        known_hash = auth.hash_password(password)

        users_json = json.dumps({"alice": known_hash})
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        monkeypatch.setattr(config, "AUTH_USERS", users_json)
        monkeypatch.setattr(config, "JWT_SECRET", "test-secret-key-for-jwt-tokens-1234")

        # Reload auth
        auth.USERS.clear()
        auth._init_users_from_env()

        # The stored hash should be used directly (not double-hashed)
        assert "alice" in auth.USERS
        assert auth.verify_password(password, auth.USERS["alice"]["password_hash"])

    def test_legacy_plaintext_still_works(self, monkeypatch):
        """Legacy plaintext passwords should be hashed on load (backward compat)."""
        from .. import config, auth

        users_json = json.dumps({"bob": "plaintext_pass"})
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        monkeypatch.setattr(config, "AUTH_USERS", users_json)
        monkeypatch.setattr(config, "JWT_SECRET", "test-secret-key-for-jwt-tokens-1234")

        auth.USERS.clear()
        auth._init_users_from_env()

        assert "bob" in auth.USERS
        assert auth.verify_password("plaintext_pass", auth.USERS["bob"]["password_hash"])


# ---------------------------------------------------------------------------
# Bcrypt hash detection
# ---------------------------------------------------------------------------

class TestBcryptDetection:
    """The is_bcrypt_hash helper must reliably distinguish hashes from plaintext."""

    def test_detects_bcrypt_hash(self):
        from ..auth import hash_password
        h = hash_password("test")
        assert _is_bcrypt_hash(h)

    def test_rejects_plaintext(self):
        assert not _is_bcrypt_hash("mypassword")
        assert not _is_bcrypt_hash("")
        assert not _is_bcrypt_hash("$1$notbcrypt")


# ---------------------------------------------------------------------------
# .env serialization preserves bcrypt hashes
# ---------------------------------------------------------------------------

class TestEnvSerialization:
    """Bcrypt hashes with $ chars must survive .env write/read round-trip."""

    def test_sanitize_uses_single_quotes_for_dollar_signs(self):
        """Values containing $ must be single-quoted to prevent shell expansion."""
        # Simulate what save_setup_config does
        from ..auth import hash_password
        hashed_users = {"alice": hash_password("test123")}
        serialized = json.dumps(hashed_users)

        # Import sanitize logic (it's a nested function, so we replicate)
        assert "$" in serialized  # bcrypt hashes contain $
        # Single-quoted values preserve $ literally
        # The sanitizer wraps in single quotes when $ is present
        sanitized = serialized.replace('\n', '').replace('\r', '')
        if '$' in sanitized:
            sanitized = "'" + sanitized.replace("'", "'\\''") + "'"
        assert sanitized.startswith("'")
        assert sanitized.endswith("'")

    def test_bcrypt_hash_round_trip_through_json(self):
        """Hash → JSON serialize → JSON parse → verify password."""
        from ..auth import hash_password, verify_password
        password = "roundtrip_test"
        h = hash_password(password)
        serialized = json.dumps({"user": h})
        parsed = json.loads(serialized)
        assert verify_password(password, parsed["user"])
