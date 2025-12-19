"""Authentication module for LLM Council with JWT + bcrypt."""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import bcrypt
import jwt
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 60

# Auth enabled flag - default FALSE for easy open source setup
# Set AUTH_ENABLED=true in production with JWT_SECRET and AUTH_USERS
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"


def validate_jwt_config():
    """
    Validate JWT configuration (called lazily when auth is actually used).

    Raises:
        ValueError: If AUTH_ENABLED=true but JWT_SECRET is not set
    """
    if AUTH_ENABLED and not JWT_SECRET:
        raise ValueError(
            "JWT_SECRET environment variable must be set when AUTH_ENABLED=true. "
            "Generate a secure secret with: openssl rand -base64 32"
        )

# User store - initialized from environment variable
USERS: Dict[str, Dict[str, str]] = {}


def _init_users_from_env():
    """
    Initialize users from AUTH_USERS environment variable.

    Format: JSON object {"username": "password", ...}
    Example: AUTH_USERS={"Alex": "mypassword", "Bob": "secret123"}

    Passwords are hashed with bcrypt at startup.
    """
    auth_users_json = os.getenv("AUTH_USERS", "{}")

    try:
        users_config = json.loads(auth_users_json)

        if not isinstance(users_config, dict):
            logger.error("AUTH_USERS must be a JSON object")
            return

        for username, password in users_config.items():
            if not username or not password:
                logger.warning(f"Skipping invalid user entry: {username}")
                continue

            USERS[username] = {
                "password_hash": bcrypt.hashpw(
                    password.encode(), bcrypt.gensalt()
                ).decode(),
                "name": username
            }

        if USERS:
            logger.info(f"Loaded {len(USERS)} users from AUTH_USERS")
        else:
            logger.warning("No users configured. Set AUTH_USERS environment variable.")

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AUTH_USERS: {e}")


# Initialize users on module load
_init_users_from_env()


class LoginRequest(BaseModel):
    """Login request model."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response model."""
    success: bool
    user: Optional[Dict[str, str]] = None
    token: Optional[str] = None
    expiresAt: Optional[int] = None
    error: Optional[str] = None


class ValidateResponse(BaseModel):
    """Token validation response model."""
    success: bool
    user: Optional[Dict[str, str]] = None
    error: Optional[str] = None


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against its hash.

    Args:
        password: Plain text password to verify
        password_hash: Bcrypt hash to verify against

    Returns:
        True if password matches, False otherwise
    """
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


def create_token(username: str) -> tuple[str, int]:
    """
    Create a signed JWT token for the user.

    Args:
        username: The username to create token for

    Returns:
        Tuple of (JWT token string, expiration timestamp in milliseconds)

    Raises:
        ValueError: If JWT_SECRET is not configured
    """
    if not JWT_SECRET:
        raise ValueError("JWT_SECRET environment variable must be set")

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=TOKEN_EXPIRE_DAYS)

    payload = {
        "sub": username,
        "iat": now,
        "exp": expires,
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    expires_at_ms = int(expires.timestamp() * 1000)

    return token, expires_at_ms


def validate_token(token: str) -> Optional[str]:
    """
    Validate a JWT token and return the username if valid.

    Args:
        token: JWT token string to validate

    Returns:
        Username if token is valid, None otherwise
    """
    if not JWT_SECRET:
        logger.error("JWT_SECRET not configured")
        return None

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")

        if username and username in USERS:
            return username
        return None
    except jwt.ExpiredSignatureError:
        logger.debug("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"Invalid token: {e}")
        return None


def authenticate(username: str, password: str) -> LoginResponse:
    """
    Authenticate a user with username and password.

    Args:
        username: The username
        password: The password

    Returns:
        LoginResponse with success status and JWT token if successful
    """
    if not username or not password:
        return LoginResponse(
            success=False,
            error="Username and password are required"
        )

    if not JWT_SECRET:
        logger.error("JWT_SECRET not configured - authentication disabled")
        return LoginResponse(
            success=False,
            error="Authentication system not configured"
        )

    user = USERS.get(username)

    if not user:
        return LoginResponse(
            success=False,
            error="Invalid username or password"
        )

    if not verify_password(password, user["password_hash"]):
        return LoginResponse(
            success=False,
            error="Invalid username or password"
        )

    try:
        token, expires_at = create_token(username)
    except ValueError as e:
        logger.error(f"Token creation failed: {e}")
        return LoginResponse(
            success=False,
            error="Authentication system error"
        )

    logger.info(f"User logged in: {username}")

    return LoginResponse(
        success=True,
        user={"username": username},
        token=token,
        expiresAt=expires_at
    )


def get_usernames() -> list[str]:
    """
    Get list of valid usernames.

    Returns:
        List of username strings
    """
    return list(USERS.keys())


def reload_auth():
    """
    Reload authentication configuration from environment.
    Call this after updating .env via setup wizard.
    """
    global JWT_SECRET, AUTH_ENABLED, USERS

    # Reload from environment (dotenv should have been reloaded first)
    from dotenv import load_dotenv
    load_dotenv(override=True)

    JWT_SECRET = os.getenv("JWT_SECRET")
    AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"

    # Clear and reload users
    USERS.clear()
    _init_users_from_env()

    logger.info(f"Auth reloaded: AUTH_ENABLED={AUTH_ENABLED}, users={len(USERS)}")


def validate_auth_token(token: str) -> ValidateResponse:
    """
    Validate an authentication token.

    Args:
        token: The JWT token to validate

    Returns:
        ValidateResponse with success status and user info if valid
    """
    if not token:
        return ValidateResponse(
            success=False,
            error="Token is required"
        )

    username = validate_token(token)

    if not username:
        return ValidateResponse(
            success=False,
            error="Invalid or expired token"
        )

    return ValidateResponse(
        success=True,
        user={"username": username}
    )
