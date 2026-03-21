"""Tests for conversation ownership enforcement (Item 01).

When AUTH_ENABLED=true, each user must only see and modify their own conversations.
Unauthorized access returns 404 (not 403) to prevent conversation ID enumeration.
When AUTH_ENABLED=false, all conversations are accessible via 'guest' identity.

Covers both the storage layer (unit) and the FastAPI route layer (integration).
"""

from __future__ import annotations

import pytest
import uuid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_json_storage(monkeypatch, tmp_path):
    """Configure storage to use JSON backend with an isolated temp dir."""
    from .. import storage

    monkeypatch.setattr(storage, "is_using_database", lambda: False)
    monkeypatch.setattr(storage.config, "DATA_DIR", str(tmp_path))
    return storage


def _create_conversation(storage_mod, username: str, conv_id: str | None = None):
    """Create a conversation owned by *username* and return its id."""

    cid = conv_id or str(uuid.uuid4())
    storage_mod.create_conversation(cid, models=None, chairman=None, username=username)
    return cid


# ---------------------------------------------------------------------------
# Scoped list
# ---------------------------------------------------------------------------

class TestScopedList:
    """list_conversations must return only conversations owned by the requesting user."""

    def test_user_sees_only_own_conversations(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        _create_conversation(storage, "alice")
        _create_conversation(storage, "alice")
        _create_conversation(storage, "bob")

        alice_convs = storage.list_conversations(username="alice")
        assert len(alice_convs) == 2
        assert all(c["username"] == "alice" for c in alice_convs)

    def test_user_sees_no_other_users_conversations(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        _create_conversation(storage, "alice")

        bob_convs = storage.list_conversations(username="bob")
        assert len(bob_convs) == 0

    def test_guest_sees_all_when_auth_disabled(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        _create_conversation(storage, "guest")
        _create_conversation(storage, None)  # legacy ownerless

        guest_convs = storage.list_conversations(username="guest")
        assert len(guest_convs) == 2


# ---------------------------------------------------------------------------
# Scoped get
# ---------------------------------------------------------------------------

class TestScopedGet:
    """get_conversation must enforce ownership."""

    def test_owner_can_get_own_conversation(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        cid = _create_conversation(storage, "alice")

        conv = storage.get_conversation(cid, username="alice")
        assert conv is not None
        assert conv["id"] == cid

    def test_non_owner_gets_none(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        cid = _create_conversation(storage, "alice")

        conv = storage.get_conversation(cid, username="bob")
        assert conv is None

    def test_guest_can_access_ownerless_conversation(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        cid = _create_conversation(storage, None)

        conv = storage.get_conversation(cid, username="guest")
        assert conv is not None

    def test_named_user_cannot_access_ownerless_conversation(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        cid = _create_conversation(storage, None)

        conv = storage.get_conversation(cid, username="alice")
        assert conv is None


# ---------------------------------------------------------------------------
# Scoped rename (update title)
# ---------------------------------------------------------------------------

class TestScopedRename:
    """update_conversation_title must enforce ownership."""

    def test_owner_can_rename(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        cid = _create_conversation(storage, "alice")

        storage.update_conversation_title(cid, "New Title", username="alice")
        conv = storage.get_conversation(cid, username="alice")
        assert conv["title"] == "New Title"

    def test_non_owner_rename_raises(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        cid = _create_conversation(storage, "alice")

        with pytest.raises(ValueError):
            storage.update_conversation_title(cid, "Hacked", username="bob")


# ---------------------------------------------------------------------------
# Scoped delete
# ---------------------------------------------------------------------------

class TestScopedDelete:
    """delete_conversation must enforce ownership."""

    def test_owner_can_delete(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        cid = _create_conversation(storage, "alice")

        result = storage.delete_conversation(cid, username="alice")
        assert result is True

    def test_non_owner_delete_returns_false(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        cid = _create_conversation(storage, "alice")

        result = storage.delete_conversation(cid, username="bob")
        assert result is False

        # Conversation still exists for alice
        conv = storage.get_conversation(cid, username="alice")
        assert conv is not None


# ---------------------------------------------------------------------------
# Scoped delete-all
# ---------------------------------------------------------------------------

class TestScopedDeleteAll:
    """delete_all_conversations must be user-scoped when username is provided."""

    def test_delete_all_only_removes_own(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        alice_id = _create_conversation(storage, "alice")
        bob_id = _create_conversation(storage, "bob")

        storage.delete_all_conversations(username="alice")

        # Alice's conversation is gone
        assert storage.get_conversation(alice_id, username="alice") is None
        # Bob's conversation still exists
        assert storage.get_conversation(bob_id, username="bob") is not None

    def test_guest_delete_all_removes_guest_and_ownerless(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        guest_id = _create_conversation(storage, "guest")
        ownerless_id = _create_conversation(storage, None)
        alice_id = _create_conversation(storage, "alice")

        storage.delete_all_conversations(username="guest")

        assert storage.get_conversation(guest_id, username="guest") is None
        assert storage.get_conversation(ownerless_id, username="guest") is None
        assert storage.get_conversation(alice_id, username="alice") is not None


# ---------------------------------------------------------------------------
# Legacy ownerless conversations
# ---------------------------------------------------------------------------

class TestLegacyOwnerless:
    """Ownerless (legacy) conversations: accessible to guest, invisible to named users."""

    def test_ownerless_visible_in_guest_list(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        _create_conversation(storage, None)

        convs = storage.list_conversations(username="guest")
        assert len(convs) == 1

    def test_ownerless_invisible_to_named_user_list(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        _create_conversation(storage, None)

        convs = storage.list_conversations(username="alice")
        assert len(convs) == 0

    def test_ownerless_invisible_to_named_user_get(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        cid = _create_conversation(storage, None)

        conv = storage.get_conversation(cid, username="alice")
        assert conv is None


# ---------------------------------------------------------------------------
# No-filtering when username=None (internal / auth-disabled bypass)
# ---------------------------------------------------------------------------

class TestNoFilteringBypass:
    """When username=None is passed, all conversations are visible (backwards compat)."""

    def test_get_without_username_returns_any_owner(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        cid = _create_conversation(storage, "alice")

        conv = storage.get_conversation(cid)  # no username
        assert conv is not None

    def test_list_without_username_returns_all(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        _create_conversation(storage, "alice")
        _create_conversation(storage, "bob")
        _create_conversation(storage, None)

        all_convs = storage.list_conversations()  # no username
        assert len(all_convs) == 3

    def test_delete_all_without_username_removes_everything(self, tmp_path, monkeypatch):
        storage = _setup_json_storage(monkeypatch, tmp_path)
        _create_conversation(storage, "alice")
        _create_conversation(storage, "bob")

        storage.delete_all_conversations()  # no username
        assert len(storage.list_conversations()) == 0


# ---------------------------------------------------------------------------
# HTTP-layer integration tests (TestClient)
# ---------------------------------------------------------------------------

class TestHTTPAuthDisabledSeesAll:
    """When AUTH_ENABLED=false, the API must expose ALL conversations regardless of owner.

    This is the regression caught by the reviewer: get_current_user returns 'guest',
    but _ownership_username returns None, so no filtering is applied.
    """

    @pytest.fixture()
    def client_auth_disabled(self, tmp_path, monkeypatch):
        from .. import storage, config
        from ..main import app

        monkeypatch.setattr(storage, "is_using_database", lambda: False)
        monkeypatch.setattr(storage.config, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(config, "AUTH_ENABLED", False)

        from starlette.testclient import TestClient
        return TestClient(app)

    def test_list_returns_all_owners(self, client_auth_disabled, tmp_path, monkeypatch):
        from .. import storage
        _create_conversation(storage, "alice")
        _create_conversation(storage, "bob")
        _create_conversation(storage, None)

        resp = client_auth_disabled.get("/api/conversations")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_get_other_users_conversation(self, client_auth_disabled, tmp_path, monkeypatch):
        from .. import storage
        cid = _create_conversation(storage, "alice")

        resp = client_auth_disabled.get(f"/api/conversations/{cid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == cid

    def test_delete_other_users_conversation(self, client_auth_disabled, tmp_path, monkeypatch):
        from .. import storage
        cid = _create_conversation(storage, "alice")

        resp = client_auth_disabled.delete(f"/api/conversations/{cid}")
        assert resp.status_code == 200

    def test_delete_all_removes_everything(self, client_auth_disabled, tmp_path, monkeypatch):
        from .. import storage
        _create_conversation(storage, "alice")
        _create_conversation(storage, "bob")

        resp = client_auth_disabled.delete("/api/conversations")
        assert resp.status_code == 200

        remaining = storage.list_conversations()
        assert len(remaining) == 0
