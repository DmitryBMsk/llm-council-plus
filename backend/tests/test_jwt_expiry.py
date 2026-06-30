"""JWT lifetime is env-configurable (B1.5).

create_token() reads JWT_EXPIRE_DAYS per call so operators can shorten the
stolen-token window without a code change; invalid values fall back to default.
"""
from datetime import datetime, timezone


def _delta_days(expires_at_ms: int) -> float:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return (expires_at_ms - now_ms) / (1000 * 60 * 60 * 24)


def test_jwt_expiry_respects_env(monkeypatch):
    from .. import auth, config
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)
    monkeypatch.setenv("JWT_EXPIRE_DAYS", "1")
    _, expires_at_ms = auth.create_token("alice")
    assert 0.9 < _delta_days(expires_at_ms) < 1.1


def test_jwt_expiry_defaults_when_unset(monkeypatch):
    from .. import auth, config
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)
    monkeypatch.delenv("JWT_EXPIRE_DAYS", raising=False)
    _, expires_at_ms = auth.create_token("bob")
    assert (auth.DEFAULT_TOKEN_EXPIRE_DAYS - 1) < _delta_days(expires_at_ms) < (auth.DEFAULT_TOKEN_EXPIRE_DAYS + 1)


def test_jwt_expiry_invalid_falls_back_to_default(monkeypatch):
    from .. import auth, config
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)
    monkeypatch.setenv("JWT_EXPIRE_DAYS", "not-a-number")
    _, expires_at_ms = auth.create_token("carol")
    assert (auth.DEFAULT_TOKEN_EXPIRE_DAYS - 1) < _delta_days(expires_at_ms) < (auth.DEFAULT_TOKEN_EXPIRE_DAYS + 1)
