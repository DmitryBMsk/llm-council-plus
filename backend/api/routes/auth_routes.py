"""Authentication endpoints — /api/auth, /api/users, /api/auth/status."""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials
from typing import Optional

from ... import config
from ...auth import LoginRequest, authenticate, validate_auth_token, get_usernames
from ..deps import security

router = APIRouter(tags=["auth"])


@router.post("/api/auth")
async def login(request: LoginRequest):
    """
    Authenticate a user with username and password.
    Returns a token on success.
    """
    result = authenticate(request.username, request.password)

    if not result.success:
        raise HTTPException(status_code=401, detail=result.error)

    return result.model_dump()


@router.get("/api/auth")
async def validate_token_endpoint(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    """
    Validate an authentication token.
    Token should be passed in Authorization header as 'Bearer <token>'.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    result = validate_auth_token(credentials.credentials)

    if not result.success:
        raise HTTPException(status_code=401, detail=result.error)

    return result.model_dump()


@router.get("/api/users")
async def get_users():
    """
    Get list of valid usernames.

    Security: Only returns usernames when AUTH_ENABLED=false (demo/dev mode).
    When auth is enabled, returns empty list to prevent exposing configured usernames.
    In production, users must enter username manually.
    """
    if config.AUTH_ENABLED:
        return {"users": []}  # Don't expose usernames in production
    return {"users": get_usernames()}


@router.get("/api/auth/status")
async def get_auth_status():
    """
    Get authentication status.
    Public endpoint - returns whether auth is enabled.
    Frontend uses this to decide whether to show login screen.
    """
    return {"auth_enabled": config.AUTH_ENABLED}
