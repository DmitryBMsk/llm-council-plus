"""Setup wizard endpoints — /api/setup/*."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Optional
from pathlib import Path
import json
import os

from ... import config

router = APIRouter(tags=["setup"])


class SetupConfigRequest(BaseModel):
    """Request to configure the application."""
    openrouter_api_key: Optional[str] = Field(default=None, min_length=10, max_length=200)
    router_type: Optional[str] = Field(default=None, pattern="^(openrouter|ollama)$")
    tavily_api_key: Optional[str] = Field(default=None, max_length=200)  # Optional: for web search
    exa_api_key: Optional[str] = Field(default=None, max_length=200)  # Optional: for AI-powered web search
    brave_api_key: Optional[str] = Field(default=None, max_length=200)  # Optional: for Brave search
    # Authentication settings
    auth_enabled: Optional[bool] = Field(default=None)
    jwt_secret: Optional[str] = Field(default=None, min_length=32, max_length=100)
    auth_users: Optional[Dict[str, str]] = Field(default=None)  # {"username": "password"}


@router.get("/api/setup/status")
async def get_setup_status():
    """
    Check if the application is properly configured.
    Returns setup_required=true if API key is missing for OpenRouter mode.
    Also returns web_search_enabled for frontend to show/hide web search option.
    """
    from ...web_search import duckduckgo_available

    needs_setup = config.ROUTER_TYPE == "openrouter" and not config.OPENROUTER_API_KEY
    # Web search is enabled if either Tavily or Exa is configured
    tavily_enabled = config.ENABLE_TAVILY and bool(config.TAVILY_API_KEY)
    exa_enabled = config.ENABLE_EXA and bool(config.EXA_API_KEY)
    brave_enabled = config.ENABLE_BRAVE and bool(config.BRAVE_API_KEY)
    duckduckgo_enabled = duckduckgo_available()
    web_search_enabled = tavily_enabled or exa_enabled or brave_enabled or duckduckgo_enabled

    return {
        "setup_required": needs_setup,
        "router_type": config.ROUTER_TYPE,
        "has_api_key": bool(config.OPENROUTER_API_KEY),
        "web_search_enabled": web_search_enabled,
        "duckduckgo_enabled": duckduckgo_enabled,
        "tavily_enabled": tavily_enabled,
        "exa_enabled": exa_enabled,
        "brave_enabled": brave_enabled,
        "message": "OpenRouter API key required" if needs_setup else "Configuration OK"
    }


@router.get("/api/setup/generate-secret")
async def generate_secret(type: str = "jwt"):
    """
    Generate a secure random secret for JWT or password.
    type: 'jwt' (44 chars base64) or 'password' (12 chars alphanumeric)
    """
    import secrets
    import string

    if type == "jwt":
        # Generate 32 bytes = 44 chars in base64 (URL-safe)
        secret = secrets.token_urlsafe(32)
        return {"secret": secret, "type": "jwt"}
    elif type == "password":
        # Generate 12 char alphanumeric password
        alphabet = string.ascii_letters + string.digits
        password = ''.join(secrets.choice(alphabet) for _ in range(12))
        return {"secret": password, "type": "password"}
    else:
        raise HTTPException(status_code=400, detail="Invalid type. Use 'jwt' or 'password'")


@router.post("/api/setup/config")
async def save_setup_config(request: SetupConfigRequest):
    """
    Save configuration to .env file.
    This endpoint is only available when setup is required (first run).
    After initial setup, this endpoint is disabled for security.
    """

    # Find .env file location
    env_path = Path(__file__).parent.parent.parent.parent / ".env"

    # Security check: Only allow setup when not yet configured
    # Check for SETUP_COMPLETE flag or existing valid configuration
    if config.ROUTER_TYPE == "openrouter" and config.OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Application is already configured. Edit .env file manually to change settings."
        )

    # For Ollama: check if setup was already completed (SETUP_COMPLETE flag in .env)
    if env_path.exists():
        try:
            env_content = env_path.read_text()
            if "SETUP_COMPLETE=true" in env_content:
                raise HTTPException(
                    status_code=403,
                    detail="Application is already configured. Edit .env file manually to change settings."
                )
        except HTTPException:
            raise  # Re-raise HTTP exceptions (don't swallow security checks)
        except OSError:
            pass  # If we can't read file, proceed with setup

    # Build new config lines
    updates = {}
    if request.router_type:
        updates["ROUTER_TYPE"] = request.router_type
    if request.openrouter_api_key:
        updates["OPENROUTER_API_KEY"] = request.openrouter_api_key
    if request.tavily_api_key:
        updates["TAVILY_API_KEY"] = request.tavily_api_key
        updates["ENABLE_TAVILY"] = "true"  # Auto-enable when key is provided
    if request.exa_api_key:
        updates["EXA_API_KEY"] = request.exa_api_key
        updates["ENABLE_EXA"] = "true"  # Auto-enable when key is provided
    if request.brave_api_key:
        updates["BRAVE_API_KEY"] = request.brave_api_key
        updates["ENABLE_BRAVE"] = "true"  # Auto-enable when key is provided
    # Authentication settings
    if request.auth_enabled is not None:
        updates["AUTH_ENABLED"] = "true" if request.auth_enabled else "false"
    if request.jwt_secret:
        updates["JWT_SECRET"] = request.jwt_secret
    if request.auth_users:
        # Hash passwords before persisting — never store plaintext.
        # Skip already-hashed values to prevent double-hashing on re-setup.
        from ...auth import hash_password, _is_bcrypt_hash
        hashed_users = {
            username: (pwd if _is_bcrypt_hash(pwd) else hash_password(pwd))
            for username, pwd in request.auth_users.items()
        }
        updates["AUTH_USERS"] = json.dumps(hashed_users)

    if not updates:
        raise HTTPException(status_code=400, detail="No configuration provided")

    # Keep raw values for os.environ (runtime), sanitize only for .env file
    raw_updates = dict(updates)

    # Sanitize values to prevent .env injection (newlines could inject new variables)
    def sanitize_env_value(value: str) -> str:
        """Remove/escape characters that could cause .env injection."""
        if not isinstance(value, str):
            return str(value)
        # Remove newlines and carriage returns (could inject new variables)
        sanitized = value.replace('\n', '').replace('\r', '')
        # Values with $ (e.g. bcrypt hashes) must use single quotes to avoid
        # shell variable expansion. Single quotes preserve $ literally.
        if '$' in sanitized:
            # Escape any embedded single quotes: ' → '\''
            sanitized = "'" + sanitized.replace("'", "'\\''") + "'"
        elif ' ' in sanitized or '"' in sanitized or "'" in sanitized or '#' in sanitized:
            # Escape existing quotes and wrap in double quotes
            sanitized = '"' + sanitized.replace('"', '\\"') + '"'
        return sanitized

    # file_updates = sanitized values for .env file
    file_updates = {k: sanitize_env_value(v) for k, v in updates.items()}

    # Read existing .env or create new
    existing_lines = []
    existing_keys = set()
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith('#') and '=' in stripped:
                    key = stripped.split('=')[0]
                    if key not in file_updates:
                        existing_lines.append(line.rstrip())
                    existing_keys.add(key)
                elif stripped:
                    existing_lines.append(line.rstrip())

    # Add new/updated values (sanitized for file)
    for key, value in file_updates.items():
        existing_lines.append(f"{key}={value}")

    # Mark setup as complete (prevents re-running setup endpoint)
    if "SETUP_COMPLETE" not in existing_keys:
        existing_lines.append("SETUP_COMPLETE=true")
        raw_updates["SETUP_COMPLETE"] = "true"

    # Write back
    with open(env_path, 'w') as f:
        f.write('\n'.join(existing_lines) + '\n')

    # CRITICAL: Directly update os.environ with RAW values (not quoted/escaped)
    # load_dotenv(override=True) doesn't override vars set by Docker at container startup
    for key, value in raw_updates.items():
        os.environ[key] = value

    # Reload config and auth modules to pick up new values in memory
    from ...auth import reload_auth
    config.reload_config()
    reload_auth()

    return {
        "success": True,
        "message": "Configuration saved successfully.",
        "restart_required": False
    }
