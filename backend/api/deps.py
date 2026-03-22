"""Shared dependencies for API route modules."""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pathlib import Path
from typing import Optional

from .. import config
from ..auth import validate_token


def get_version() -> str:
    """Read version from VERSION file."""
    version_file = Path(__file__).parent.parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "unknown"


VERSION = get_version()

# Security scheme for protected endpoints
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> str:
    """
    Validate JWT token and return username.
    Used as a dependency for protected endpoints.
    When AUTH_ENABLED=false, returns 'guest' without validation.
    """
    # Skip authentication when disabled
    if not config.AUTH_ENABLED:
        return "guest"

    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )

    username = validate_token(credentials.credentials)
    if not username:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return username


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[str]:
    """
    Optionally validate JWT token. Returns username if valid, None otherwise.
    Used for endpoints that work with or without authentication.
    """
    if not credentials:
        return None

    return validate_token(credentials.credentials)


def _ownership_username(current_user: str) -> Optional[str]:
    """Return username for ownership filtering, or None when auth is disabled.

    When AUTH_ENABLED=false all conversations are shared — no ownership filtering.
    When AUTH_ENABLED=true each user sees only their own conversations.
    """
    if not config.AUTH_ENABLED:
        return None
    return current_user
