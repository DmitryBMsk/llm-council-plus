"""FastAPI backend for LLM-TTCC-TEAM-PRO."""

from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import uuid
import json
import asyncio
import time
import logging
import httpx
import os

# Configure logging based on LOG_LEVEL env var (default: INFO)
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)

logger = logging.getLogger(__name__)


def get_version() -> str:
    """Read version from VERSION file."""
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "unknown"


VERSION = get_version()

from . import storage
from .council import (
    run_full_council, generate_conversation_title,
    stage1_collect_responses, stage1_collect_responses_streaming,
    stage2_collect_rankings, stage3_synthesize_final,
    calculate_aggregate_rankings, reset_token_stats, get_token_stats
)
from .file_parser import parse_file, get_supported_extensions, is_image_file
from .auth import LoginRequest, authenticate, validate_auth_token, validate_token, get_usernames, validate_jwt_config
from . import config
from .gdrive import upload_to_drive, get_drive_status, is_drive_configured
from .database import init_database
from .runtime_settings import (
    RuntimeSettings,
    get_runtime_settings,
    update_runtime_settings,
    reset_runtime_settings,
    default_runtime_settings,
    save_runtime_settings,
)

app = FastAPI(title="LLM-TTCC-TEAM-PRO API")

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


# Initialize on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database and validate configuration at startup."""
    # Validate JWT configuration if auth is enabled
    validate_jwt_config()
    # Initialize database tables if using database storage (Feature 2: Multi-DB support)
    init_database()

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5175", "http://localhost:3000", "http://localhost", "https://localhost", "http://127.0.0.1", "http://127.0.0.1:80"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    models: Optional[List[str]] = Field(default=None, max_length=20)  # Council models (max 20)
    chairman: Optional[str] = Field(default=None, max_length=100)  # Chairman/judge model
    username: Optional[str] = Field(default=None, max_length=50)  # User who created the conversation
    execution_mode: Optional[str] = Field(default=None, pattern="^(chat_only|chat_ranking|full)$")
    router_type: Optional[str] = Field(default=None, pattern="^(openrouter|ollama)$")
    system_prompt: Optional[str] = Field(default=None, max_length=200_000)  # Custom system prompt (e.g., TTCC mode)


class FileAttachment(BaseModel):
    """File attachment with parsed content."""
    filename: str = Field(max_length=255, pattern=r'^[^/\\<>:"|?*\x00-\x1f]+$')  # Safe filename
    file_type: str = Field(max_length=20)  # 'pdf', 'txt', 'md', or 'image'
    content: str = Field(max_length=5_000_000)  # 5MB limit per file (base64)
    mime_type: Optional[str] = Field(default=None, max_length=100)


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str = Field(min_length=1, max_length=100_000)  # 100KB text limit
    attachments: Optional[List[FileAttachment]] = Field(default=None, max_length=5)  # Max 5 attachments
    temporary: Optional[bool] = False  # If True, don't save to storage (Feature 5)
    web_search: Optional[bool] = False  # DEPRECATED: use web_search_provider
    web_search_provider: Optional[str] = Field(default=None, pattern="^(duckduckgo|tavily|exa|brave)$")

    @field_validator('attachments')
    @classmethod
    def validate_total_attachment_size(cls, v):
        """Validate total size of all attachments (max 20MB total)."""
        if v is None:
            return v
        total_size = sum(len(att.content) for att in v)
        max_total_size = 20_000_000  # 20MB total
        if total_size > max_total_size:
            raise ValueError(f"Total attachment size ({total_size / 1_000_000:.1f}MB) exceeds limit (20MB)")
        return v


class UpdateTitleRequest(BaseModel):
    """Request to update conversation title (Feature 5)."""
    title: str = Field(min_length=1, max_length=200)  # Reasonable title length


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int
    username: Optional[str] = None


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]
    models: Optional[List[str]] = None
    chairman: Optional[str] = None
    username: Optional[str] = None
    execution_mode: Optional[str] = None
    system_prompt: Optional[str] = None


class UpdateRuntimeSettingsRequest(BaseModel):
    """Partial update for runtime settings (non-secret)."""

    stage1_prompt_template: Optional[str] = Field(default=None, max_length=200_000)
    stage2_prompt_template: Optional[str] = Field(default=None, max_length=200_000)
    stage3_prompt_template: Optional[str] = Field(default=None, max_length=200_000)

    council_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    stage2_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    chairman_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)

    web_search_provider: Optional[str] = Field(default=None, pattern="^(off|duckduckgo|tavily|exa|brave)$")
    web_max_results: Optional[int] = Field(default=None, ge=1, le=10)
    web_full_content_results: Optional[int] = Field(default=None, ge=0, le=10)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM-TTCC-TEAM-PRO API", "version": VERSION}


@app.get("/api/version")
async def get_api_version():
    """Get API version."""
    return {"version": VERSION}

# ==================== Runtime Settings (Non-secret) ====================


@app.get("/api/settings")
async def get_settings_endpoint(current_user: str = Depends(get_current_user)):
    """Get runtime settings (prompt templates + temperatures)."""
    return get_runtime_settings().model_dump()


@app.patch("/api/settings")
async def update_settings_endpoint(
    request: UpdateRuntimeSettingsRequest,
    current_user: str = Depends(get_current_user),
):
    """Patch runtime settings (non-secret)."""
    patch = {k: v for k, v in request.model_dump().items() if v is not None}
    updated = update_runtime_settings(**patch) if patch else get_runtime_settings()
    return updated.model_dump()


@app.get("/api/settings/defaults")
async def get_settings_defaults_endpoint(current_user: str = Depends(get_current_user)):
    """Get default runtime settings."""
    return default_runtime_settings().model_dump()


@app.post("/api/settings/reset")
async def reset_settings_endpoint(current_user: str = Depends(get_current_user)):
    """Reset runtime settings to defaults."""
    return reset_runtime_settings().model_dump()


@app.get("/api/settings/export")
async def export_settings_endpoint(current_user: str = Depends(get_current_user)):
    """Export runtime settings as JSON (same shape as GET /api/settings)."""
    return get_runtime_settings().model_dump()


@app.post("/api/settings/import")
async def import_settings_endpoint(
    request: Dict[str, Any],
    current_user: str = Depends(get_current_user),
):
    """Import runtime settings from JSON (API keys are never part of this schema)."""
    # Defense in depth: accept any JSON object but persist only the RuntimeSettings allowlist.
    allowed = set(RuntimeSettings.model_fields.keys())
    sanitized = {k: v for k, v in (request or {}).items() if k in allowed}
    settings = RuntimeSettings(**sanitized)
    save_runtime_settings(settings)
    return settings.model_dump()


# ==================== Setup Wizard Endpoints ====================

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


@app.get("/api/setup/status")
async def get_setup_status():
    """
    Check if the application is properly configured.
    Returns setup_required=true if API key is missing for OpenRouter mode.
    Also returns web_search_enabled for frontend to show/hide web search option.
    """
    from .web_search import duckduckgo_available

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


@app.get("/api/setup/generate-secret")
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


@app.get("/api/system-prompt-presets")
async def get_system_prompt_presets():
    """
    Return available system prompt presets (e.g., TTCC mode).
    Reads the TTCC system prompt from the bundled file.
    """
    presets = [{"id": "general", "name": "General (No System Prompt)", "prompt": None}]

    # Load TTCC system prompt from file
    ttcc_paths = [
        Path(__file__).parent.parent / "Technical_Training_Course_Creator_System_Prompt.md",
        Path(__file__).parent / "Technical_Training_Course_Creator_System_Prompt.md",
    ]
    for ttcc_path in ttcc_paths:
        if ttcc_path.exists():
            try:
                raw_content = ttcc_path.read_text(encoding="utf-8")
                # Extract only the content between <SYSTEM_PROMPT_START> and <SYSTEM_PROMPT_END>
                start_marker = "<SYSTEM_PROMPT_START>"
                end_marker = "<SYSTEM_PROMPT_END>"
                start_idx = raw_content.find(start_marker)
                end_idx = raw_content.find(end_marker)
                if start_idx != -1 and end_idx != -1:
                    prompt_content = raw_content[start_idx + len(start_marker):end_idx].strip()
                else:
                    prompt_content = raw_content
                presets.append({
                    "id": "ttcc",
                    "name": "Technical Training Course Creator (TTCC)",
                    "prompt": prompt_content,
                })
            except Exception as e:
                logger.warning("Failed to load TTCC system prompt: %s", e)
            break

    return {"presets": presets}


@app.post("/api/setup/config")
async def save_setup_config(request: SetupConfigRequest):
    """
    Save configuration to .env file.
    This endpoint is only available when setup is required (first run).
    After initial setup, this endpoint is disabled for security.
    """
    from pathlib import Path

    # Find .env file location
    env_path = Path(__file__).parent.parent / ".env"

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
        # Serialize users dict to JSON string
        updates["AUTH_USERS"] = json.dumps(request.auth_users)

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
        # If value contains spaces, quotes, or # (comment char), quote it
        if ' ' in sanitized or '"' in sanitized or "'" in sanitized or '#' in sanitized:
            # Escape existing quotes and wrap in quotes
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
    from .auth import reload_auth
    config.reload_config()
    reload_auth()

    return {
        "success": True,
        "message": "Configuration saved successfully.",
        "restart_required": False
    }


# ==================== Models Endpoint ====================

# Cache for models per router_type (5 minute TTL)
# Shape: { "openrouter": {"data": {...}, "timestamp": 123}, "ollama": {...} }
_models_cache: Dict[str, Dict[str, Any]] = {}
_models_cache_lock: Optional[asyncio.Lock] = None  # Initialized lazily for event-loop safety
_MODELS_CACHE_TTL = 300  # 5 minutes


def _get_models_cache_lock() -> asyncio.Lock:
    """Get or create the models cache lock (lazy init for event-loop safety)."""
    global _models_cache_lock
    if _models_cache_lock is None:
        _models_cache_lock = asyncio.Lock()
    return _models_cache_lock


def _parse_price(price_str: str) -> float:
    """Parse price string to float (per million tokens)."""
    try:
        # Price is per token, convert to per million
        price_per_token = float(price_str)
        return price_per_token * 1_000_000
    except (ValueError, TypeError):
        return 0.0


def _format_price(price_per_million: float) -> str:
    """Format price per million tokens as human-readable string."""
    if price_per_million == 0:
        return "FREE"
    elif price_per_million < 0.01:
        return f"${price_per_million:.4f}/M"
    elif price_per_million < 1:
        return f"${price_per_million:.2f}/M"
    else:
        return f"${price_per_million:.0f}/M"


def _format_context(context_length: int) -> str:
    """Format context length as human-readable string."""
    if context_length >= 1_000_000:
        return f"{context_length / 1_000_000:.1f}M"
    elif context_length >= 1000:
        return f"{context_length // 1000}K"
    else:
        return str(context_length)


def _get_tier(input_price: float, output_price: float, is_free: bool) -> str:
    """Determine pricing tier based on output price."""
    if is_free:
        return "free"
    # Based on output price per million tokens
    if output_price >= 10:
        return "premium"
    elif output_price >= 1:
        return "standard"
    else:
        return "budget"


def _extract_provider(model_id: str, model_name: str) -> str:
    """Extract provider name from model ID or name."""
    # Try to get from ID (format: provider/model-name)
    if "/" in model_id:
        provider_slug = model_id.split("/")[0]
        # Map common slugs to proper names
        provider_map = {
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "google": "Google",
            "meta-llama": "Meta",
            "mistralai": "Mistral",
            "cohere": "Cohere",
            "x-ai": "xAI",
            "deepseek": "DeepSeek",
            "nvidia": "NVIDIA",
            "amazon": "Amazon",
            "microsoft": "Microsoft",
            "qwen": "Alibaba",
            "perplexity": "Perplexity",
            "01-ai": "01.AI",
            "databricks": "Databricks",
            "allenai": "AllenAI",
            "tngtech": "TNG Tech",
            "moonshotai": "MoonshotAI",
            "z-ai": "Z.AI",
        }
        return provider_map.get(provider_slug, provider_slug.title())

    # Fallback: extract from model name
    if ":" in model_name:
        return model_name.split(":")[0].strip()
    return "Unknown"


@app.get("/api/models")
async def get_available_models(router_type: Optional[str] = None):
    """
    Get available models from OpenRouter or Ollama.
    Returns formatted model list with pricing and capabilities.
    Cached for 5 minutes to reduce API calls.
    """
    effective_router_type = (router_type or config.ROUTER_TYPE or "openrouter").lower()
    if effective_router_type not in {"openrouter", "ollama"}:
        raise HTTPException(status_code=400, detail="Invalid router_type. Must be 'openrouter' or 'ollama'.")

    # Check cache with lock for thread safety
    async with _get_models_cache_lock():
        cache_entry = _models_cache.get(effective_router_type)
        if cache_entry and cache_entry.get("data") and (time.time() - cache_entry.get("timestamp", 0)) < _MODELS_CACHE_TTL:
            return cache_entry["data"]

    if effective_router_type == "ollama":
        # Fetch from Ollama local API
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://{config.OLLAMA_HOST}/api/tags", timeout=10.0)
                if response.status_code != 200:
                    raise HTTPException(status_code=503, detail="Failed to fetch Ollama models")

                data = response.json()
                models = []
                for model in data.get("models", []):
                    models.append({
                        "id": model["name"],
                        "name": model["name"],
                        "provider": "Ollama (Local)",
                        "context": "N/A",
                        "contextLength": config.MIN_CHAIRMAN_CONTEXT,
                        "inputPrice": "FREE",
                        "outputPrice": "FREE",
                        "tier": "free",
                        "isFree": True,
                        "description": f"Local model: {model.get('details', {}).get('family', 'Unknown')}",
                        "modality": "text->text",
                    })

                result = {"models": models, "router_type": "ollama", "max_models": config.MAX_COUNCIL_MODELS}
                async with _get_models_cache_lock():
                    _models_cache[effective_router_type] = {"data": result, "timestamp": time.time()}
                return result

        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Cannot connect to Ollama: {str(e)}")

    else:
        # Fetch from OpenRouter API
        if not config.OPENROUTER_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="OpenRouter API key not configured. Complete setup first."
            )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
                    timeout=30.0
                )

                if response.status_code != 200:
                    raise HTTPException(
                        status_code=503,
                        detail=f"OpenRouter API error: {response.status_code}"
                    )

                data = response.json()
                models = []

                for model in data.get("data", []):
                    model_id = model.get("id", "")
                    model_name = model.get("name", model_id)

                    # Parse pricing
                    pricing = model.get("pricing", {})
                    input_price = _parse_price(pricing.get("prompt", "0"))
                    output_price = _parse_price(pricing.get("completion", "0"))
                    is_free = input_price == 0 and output_price == 0

                    # Get context length
                    context_length = model.get("context_length", 0)
                    top_provider = model.get("top_provider", {})
                    if top_provider.get("context_length"):
                        context_length = top_provider["context_length"]

                    # Get modality
                    arch = model.get("architecture", {})
                    modality = arch.get("modality", "text->text")
                    input_modalities = arch.get("input_modalities", ["text"])

                    models.append({
                        "id": model_id,
                        "name": model_name,
                        "provider": _extract_provider(model_id, model_name),
                        "context": _format_context(context_length),
                        "contextLength": context_length,
                        "inputPrice": _format_price(input_price),
                        "outputPrice": _format_price(output_price),
                        "inputPriceRaw": input_price,
                        "outputPriceRaw": output_price,
                        "tier": _get_tier(input_price, output_price, is_free),
                        "isFree": is_free,
                        "description": model.get("description", "")[:200],  # Truncate long descriptions
                        "modality": modality,
                        "supportsImages": "image" in input_modalities,
                        "supportsAudio": "audio" in input_modalities,
                    })

                # Sort by output price (cheapest first), then by name
                models.sort(key=lambda m: (m["outputPriceRaw"], m["name"]))

                result = {"models": models, "router_type": "openrouter", "count": len(models), "max_models": config.MAX_COUNCIL_MODELS}
                async with _get_models_cache_lock():
                    _models_cache[effective_router_type] = {"data": result, "timestamp": time.time()}
                return result

        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Failed to fetch models: {str(e)}")


# ==================== Auth Endpoints ====================

@app.post("/api/auth")
async def login(request: LoginRequest):
    """
    Authenticate a user with username and password.
    Returns a token on success.
    """
    result = authenticate(request.username, request.password)

    if not result.success:
        raise HTTPException(status_code=401, detail=result.error)

    return result.model_dump()


@app.get("/api/auth")
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


@app.get("/api/users")
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


@app.get("/api/auth/status")
async def get_auth_status():
    """
    Get authentication status.
    Public endpoint - returns whether auth is enabled.
    Frontend uses this to decide whether to show login screen.
    """
    return {"auth_enabled": config.AUTH_ENABLED}


# ==================== Conversation Endpoints ====================

@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations(current_user: str = Depends(get_current_user)):
    """List all conversations (metadata only). Requires authentication."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(
    request: CreateConversationRequest,
    current_user: str = Depends(get_current_user)
):
    """Create a new conversation. Requires authentication."""
    # Validate chairman model context length if specified
    router_type = (getattr(request, "router_type", None) or config.ROUTER_TYPE or "openrouter").strip().lower()
    async with _get_models_cache_lock():
        cache_entry = _models_cache.get(router_type)
    if request.chairman and cache_entry and cache_entry.get("data"):
        models = cache_entry["data"].get("models", [])
        chairman_model = next((m for m in models if m["id"] == request.chairman), None)
        if chairman_model:
            context_length = chairman_model.get("contextLength", 0)
            if context_length < config.MIN_CHAIRMAN_CONTEXT:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Chairman model {request.chairman} has insufficient context length "
                        f"({context_length}). Minimum required: {config.MIN_CHAIRMAN_CONTEXT}"
                    ),
                )

    conversation_id = str(uuid.uuid4())
    # Use authenticated user if not specified in request
    username = request.username or current_user
    conversation = storage.create_conversation(
        conversation_id,
        models=request.models,
        chairman=request.chairman,
        username=username,
        execution_mode=request.execution_mode or "full",
        router_type=router_type,
        system_prompt=request.system_prompt,
    )
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: str,
    current_user: str = Depends(get_current_user)
):
    """Get a specific conversation with all its messages. Requires authentication."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: str = Depends(get_current_user)
):
    """Delete a specific conversation. Requires authentication."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    storage.delete_conversation(conversation_id)
    return {"status": "deleted", "id": conversation_id}


@app.patch("/api/conversations/{conversation_id}/title")
async def update_title(
    conversation_id: str,
    request: UpdateTitleRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Update the title of a conversation (Feature 5). Requires authentication.
    Works with all storage backends: JSON, PostgreSQL, MySQL.
    """
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    storage.update_conversation_title(conversation_id, request.title)

    return {
        "success": True,
        "message": "Title updated",
        "title": request.title
    }


@app.delete("/api/conversations")
async def delete_all_conversations(current_user: str = Depends(get_current_user)):
    """Delete all conversations. Requires authentication."""
    storage.delete_all_conversations()
    return {"status": "deleted", "count": "all"}


@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user)
):
    """
    Upload and parse a file (PDF, TXT, MD, MDX, or images). Requires authentication.
    Returns the parsed content that can be attached to a message.
    For images, returns base64 data URI.
    """
    # Check file extension
    supported = get_supported_extensions()
    filename = file.filename or "unknown"
    ext = '.' + filename.lower().split('.')[-1] if '.' in filename else ''

    if ext not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Supported: {', '.join(supported)}"
        )

    try:
        # Read file content
        file_content = await file.read()

        # Check file size for images (max 20MB)
        max_image_size = 20 * 1024 * 1024  # 20MB
        if is_image_file(filename) and len(file_content) > max_image_size:
            raise HTTPException(
                status_code=400,
                detail=f"Image file too large. Maximum size is 20MB."
            )

        # Parse the file
        parsed_content, file_type = parse_file(filename, file_content)

        # Build response
        response = {
            "filename": filename,
            "file_type": file_type,
            "content": parsed_content,
        }

        # For images, add mime_type and byte size instead of char_count
        if file_type == 'image':
            from .file_parser import get_image_mime_type
            response["mime_type"] = get_image_mime_type(filename)
            response["byte_size"] = len(file_content)
            response["char_count"] = 0  # For compatibility with existing frontend
        else:
            # Truncate text content if too long (to avoid token limits)
            max_chars = 50000  # ~12.5k tokens approximately
            if len(parsed_content) > max_chars:
                parsed_content = parsed_content[:max_chars] + "\n\n... [Content truncated due to length]"
                response["content"] = parsed_content
            response["char_count"] = len(parsed_content)

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error parsing file: {str(e)}"
        )


def separate_attachments(attachments: Optional[List[FileAttachment]]) -> Tuple[List[FileAttachment], List[Dict[str, str]]]:
    """
    Separate text attachments from image attachments.

    Args:
        attachments: List of file attachments

    Returns:
        Tuple of (text_attachments, image_attachments)
        image_attachments are formatted for multimodal API
    """
    if not attachments:
        return [], []

    text_attachments = []
    image_attachments = []

    for att in attachments:
        if att.file_type == 'image':
            # Format for multimodal API
            image_attachments.append({
                "content": att.content,  # base64 data URI
                "filename": att.filename
            })
        else:
            text_attachments.append(att)

    return text_attachments, image_attachments


def build_query_with_attachments(content: str, attachments: Optional[List[FileAttachment]]) -> str:
    """Build full query including text file attachments (not images)."""
    if not attachments:
        return content

    # Filter out image attachments - they're handled separately
    text_attachments = [att for att in attachments if att.file_type != 'image']

    if not text_attachments:
        return content

    attachment_texts = []
    for att in text_attachments:
        attachment_texts.append(f"--- File: {att.filename} ({att.file_type}) ---\n{att.content}\n--- End of {att.filename} ---")

    attachments_section = "\n\n".join(attachment_texts)

    return f"""{content}

The user has attached the following file(s) for analysis:

{attachments_section}

Please analyze the attached content in the context of the user's question."""


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Send a message and run the 3-stage council process. Requires authentication.
    Returns the complete response with all stages.

    Supports temporary mode (Feature 5): if request.temporary=True,
    conversation is not saved to storage.
    """
    # Separate image attachments from text attachments
    _, image_attachments = separate_attachments(request.attachments)

    # Build full query with text attachments only (images handled separately)
    full_query = build_query_with_attachments(request.content, request.attachments)

    # For temporary mode, skip conversation existence check and storage operations
    if request.temporary:
        # Run the 3-stage council process without saving
        try:
            stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
                full_query,
                conversation_history=None,
                images=image_attachments if image_attachments else None,
                conversation_id=None  # No conversation_id for temporary chat
            )
        except ValueError as e:
            # Translate configuration errors (e.g., no council models) to 400
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "stage1": stage1_results,
            "stage2": stage2_results,
            "stage3": stage3_result,
            "metadata": metadata,
            "temporary": True
        }

    # Normal mode: save to storage
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message (store original content, not with attachments)
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Get conversation history for context (exclude the just-added user message)
    conversation_history = conversation["messages"]  # History before current question

    # Run the 3-stage council process with full query including attachments
    images_for_council = image_attachments if image_attachments else None
    try:
        stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
            full_query,
            conversation_history,
            images=images_for_council,
            conversation_id=conversation_id  # For memory system
        )
    except ValueError as e:
        # Translate configuration errors (e.g., no council models) to 400
        raise HTTPException(status_code=400, detail=str(e))

    # Add assistant message with all stages and metadata
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result,
        metadata
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Send a message and stream the 3-stage council process. Requires authentication.
    Returns Server-Sent Events as each stage completes.
    Supports multimodal queries with image attachments.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Separate image attachments from text attachments
    _, image_attachments = separate_attachments(request.attachments)

    # Build full query with text attachments only (images handled separately)
    full_query = build_query_with_attachments(request.content, request.attachments)

    # Get conversation history for context (before adding new message)
    conversation_history = conversation["messages"]

    # Get custom models, chairman, and system prompt from conversation (if set)
    conv_models = conversation.get("models")
    conv_chairman = conversation.get("chairman")
    conv_system_prompt = conversation.get("system_prompt")
    execution_mode = (conversation.get("execution_mode") or "full").strip().lower()
    router_type = (conversation.get("router_type") or config.ROUTER_TYPE or "openrouter").strip().lower()
    if router_type not in {"openrouter", "ollama"}:
        router_type = config.ROUTER_TYPE
    if execution_mode not in {"chat_only", "chat_ranking", "full"}:
        execution_mode = "full"

    async def event_generator():
        # Initialize state variables OUTSIDE try block so finally can access them
        stage1_results = []
        stage2_results = []
        stage3_result = None
        tool_outputs = []
        label_to_model = {}
        aggregate_rankings = []
        message_saved = False  # Track if message was saved in normal flow
        title_task = None
        stage2_task = None
        stage3_task = None

        try:
            # Reset token stats for this request
            reset_token_stats()

            # Add user message (store original content, not with attachments)
            storage.add_user_message(conversation_id, request.content)

            # Start title generation in parallel (don't await yet)
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content, router_type=router_type))

            # Stage 1: Collect responses with streaming - send each model's response as it completes
            # Pass images for multimodal queries
            stage1_start_time = time.time()
            yield f"data: {json.dumps({'type': 'stage1_start', 'timestamp': stage1_start_time})}\n\n"

            images_for_council = image_attachments if image_attachments else None
            # Determine web search provider (prefer explicit provider, fallback to legacy boolean)
            web_search_provider = (
                getattr(request, "web_search_provider", None)
                or ("tavily" if getattr(request, "web_search", False) else None)
            )

            try:
                async for item in stage1_collect_responses_streaming(
                    full_query,
                    conversation_history,
                    conv_models,
                    images_for_council,
                    conversation_id,
                    web_search_provider=web_search_provider,
                    chairman=conv_chairman,
                    router_type=router_type,
                    system_prompt=conv_system_prompt,
                ):
                    # Handle tool_outputs message (first yield if tools were used)
                    if item.get("type") == "tool_outputs":
                        tool_outputs = item.get("tool_outputs", [])
                        yield f"data: {json.dumps({'type': 'tool_outputs', 'data': tool_outputs, 'timestamp': time.time()})}\n\n"
                    else:
                        # Send individual model response event
                        model_time = time.time()
                        yield f"data: {json.dumps({'type': 'stage1_model_response', 'data': item, 'timestamp': model_time})}\n\n"
                        stage1_results.append(item)
            except ValueError as e:
                # Configuration errors (e.g., no council models) - send error event and stop
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                return

            stage1_end_time = time.time()
            stage1_duration = stage1_end_time - stage1_start_time
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results, 'timestamp': stage1_end_time, 'duration': stage1_duration})}\n\n"

            # Execution mode: chat_only stops after Stage 1
            if execution_mode == "chat_only":
                token_stats = get_token_stats()
                metadata = {
                    "execution_mode": execution_mode,
                    "tool_outputs": tool_outputs,
                    "token_stats": token_stats,
                }
                storage.add_assistant_message(
                    conversation_id,
                    stage1_results,
                    None,
                    None,
                    metadata
                )
                message_saved = True

                if token_stats.get('total'):
                    yield f"data: {json.dumps({'type': 'token_stats', 'data': token_stats})}\n\n"

                if title_task:
                    title = await title_task
                    storage.update_conversation_title(conversation_id, title)
                    yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                return

            # Stage 2: Collect rankings with heartbeat to prevent CloudFront timeout
            stage2_start_time = time.time()
            yield f"data: {json.dumps({'type': 'stage2_start', 'timestamp': stage2_start_time})}\n\n"

            # Run Stage 2 with periodic heartbeats (CloudFront times out after ~30s without data)
            stage2_task = asyncio.create_task(
                stage2_collect_rankings(full_query, stage1_results, conv_models, router_type=router_type)
            )
            heartbeat_interval = 15  # Send heartbeat every 15 seconds
            heartbeat_count = 0
            while not stage2_task.done():
                try:
                    # Wait for task to complete OR timeout for heartbeat
                    await asyncio.wait_for(asyncio.shield(stage2_task), timeout=heartbeat_interval)
                except asyncio.TimeoutError:
                    # Task still running, send heartbeat to keep connection alive
                    heartbeat_count += 1
                    logger.info("[STREAMING] Sending Stage 2 heartbeat #%d", heartbeat_count)
                    yield f"data: {json.dumps({'type': 'heartbeat', 'stage': 'stage2', 'timestamp': time.time()})}\n\n"

            logger.info("[STREAMING] Stage 2 task finished, getting result...")
            try:
                stage2_results, label_to_model = stage2_task.result()
                logger.info("[STREAMING] Stage 2 got %d results", len(stage2_results))
            except Exception as task_error:
                logger.error("[STREAMING] Stage 2 task.result() raised: %s: %s", type(task_error).__name__, task_error)
                raise

            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            logger.info("[STREAMING] Rankings calculated: %d entries", len(aggregate_rankings))
            stage2_end_time = time.time()
            stage2_duration = stage2_end_time - stage2_start_time

            logger.info("[STREAMING] About to yield stage2_complete (%d results)", len(stage2_results))
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}, 'timestamp': stage2_end_time, 'duration': stage2_duration})}\n\n"
            logger.info("[STREAMING] Stage 2 complete yielded successfully, proceeding to Stage 3")

            # Execution mode: chat_ranking stops after Stage 2
            if execution_mode == "chat_ranking":
                token_stats = get_token_stats()
                metadata = {
                    "execution_mode": execution_mode,
                    "label_to_model": label_to_model,
                    "aggregate_rankings": aggregate_rankings,
                    "tool_outputs": tool_outputs,
                    "token_stats": token_stats,
                }
                storage.add_assistant_message(
                    conversation_id,
                    stage1_results,
                    stage2_results,
                    None,
                    metadata
                )
                message_saved = True

                if token_stats.get('total'):
                    yield f"data: {json.dumps({'type': 'token_stats', 'data': token_stats})}\n\n"

                if title_task:
                    title = await title_task
                    storage.update_conversation_title(conversation_id, title)
                    yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                return

            # Stage 3: Synthesize final answer with heartbeat
            stage3_start_time = time.time()
            logger.info("[STREAMING] Starting Stage 3")
            yield f"data: {json.dumps({'type': 'stage3_start', 'timestamp': stage3_start_time})}\n\n"

            # Run Stage 3 with periodic heartbeats
            stage3_task = asyncio.create_task(
                stage3_synthesize_final(
                    full_query,
                    stage1_results,
                    stage2_results,
                    conv_chairman,
                    tool_outputs=tool_outputs,
                    router_type=router_type,
                )
            )
            heartbeat_count = 0
            while not stage3_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(stage3_task), timeout=heartbeat_interval)
                except asyncio.TimeoutError:
                    heartbeat_count += 1
                    logger.info("[STREAMING] Sending Stage 3 heartbeat #%d", heartbeat_count)
                    yield f"data: {json.dumps({'type': 'heartbeat', 'stage': 'stage3', 'timestamp': time.time()})}\n\n"

            logger.info("[STREAMING] Stage 3 completed after %d heartbeats", heartbeat_count)
            stage3_result = stage3_task.result()
            stage3_end_time = time.time()
            stage3_duration = stage3_end_time - stage3_start_time

            # Get accumulated token stats from TOON encoding
            token_stats = get_token_stats()

            # CRITICAL FIX: Save assistant message IMMEDIATELY after stage3 completes
            # This ensures the message is saved even if client disconnects during streaming
            # Previously, save was at the end of generator which never executed on disconnect
            metadata = {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings, 'tool_outputs': tool_outputs, 'token_stats': token_stats}
            storage.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result,
                metadata
            )
            message_saved = True  # Mark as saved to prevent duplicate save in finally

            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result, 'timestamp': stage3_end_time, 'duration': stage3_duration})}\n\n"

            # Send token stats event (TOON encoding savings)
            if token_stats.get('total'):
                yield f"data: {json.dumps({'type': 'token_stats', 'data': token_stats})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except asyncio.CancelledError:
            # Client disconnected - re-raise to allow proper generator cleanup
            # The finally block below will save partial results
            logger.info("[STREAMING] Client disconnected (CancelledError) during streaming for conversation %s", conversation_id)
            raise
        except GeneratorExit:
            # Generator closed by consumer (client disconnected)
            # This is the more common case for SSE client disconnection
            logger.info("[STREAMING] Client disconnected (GeneratorExit) during streaming for conversation %s", conversation_id)
            raise
        except Exception as e:
            logger.error("[STREAMING] Exception during streaming for conversation %s: %s: %s", conversation_id, type(e).__name__, str(e))
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        except BaseException as e:
            # Catch ALL exceptions including SystemExit, KeyboardInterrupt, etc.
            # to understand what's causing the generator to stop
            logger.error("[STREAMING] BaseException during streaming for conversation %s: %s: %s", conversation_id, type(e).__name__, str(e))
            raise
        finally:
            # Best-effort: cancel any in-flight tasks on disconnect/abort.
            tasks_to_cleanup = [t for t in (title_task, stage2_task, stage3_task) if t is not None and not t.done()]
            for task in tasks_to_cleanup:
                task.cancel()
            # Await cancelled tasks to prevent "task was destroyed but pending" warnings
            # Use shield to protect cleanup from cancellation, and handle CancelledError
            # (which is a BaseException in Python 3.8+, not caught by except Exception)
            if tasks_to_cleanup:
                try:
                    await asyncio.shield(asyncio.gather(*tasks_to_cleanup, return_exceptions=True))
                except asyncio.CancelledError:
                    pass  # Cleanup was interrupted by cancellation, tasks are already cancelled
                except Exception:
                    pass  # Ignore other cleanup errors

            # CRITICAL FIX: Save partial results if client disconnected before completion
            # This ensures we don't lose work when client closes connection mid-stream
            if not message_saved and stage1_results:
                logger.info("[STREAMING] Saving partial results for conversation %s (stage1=%d, stage2=%d, stage3=%s)", conversation_id, len(stage1_results), len(stage2_results), 'yes' if stage3_result else 'no')
                partial_metadata = {
                    'label_to_model': label_to_model,
                    'aggregate_rankings': aggregate_rankings,
                    'tool_outputs': tool_outputs,
                    'partial': True,  # Mark as partial results
                    'stages_completed': {
                        'stage1': len(stage1_results) > 0,
                        'stage2': len(stage2_results) > 0,
                        'stage3': stage3_result is not None
                    }
                }
                try:
                    storage.add_assistant_message(
                        conversation_id,
                        stage1_results,
                        stage2_results,
                        stage3_result,
                        partial_metadata
                    )
                    logger.info("[STREAMING] Partial results saved successfully for conversation %s", conversation_id)
                except Exception as save_error:
                    logger.error("[STREAMING] Failed to save partial results: %s", save_error)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream; charset=utf-8",
            "X-Accel-Buffering": "no",  # Disable nginx buffering for real-time SSE
        }
    )


# ==================== Google Drive Endpoints ====================

class DriveUploadRequest(BaseModel):
    """Request to upload content to Google Drive."""
    filename: str = Field(max_length=255, pattern=r'^[^/\\<>:"|?*\x00-\x1f]+$')  # Safe filename
    content: str = Field(max_length=10_000_000)  # 10MB content limit


@app.get("/api/drive/status")
async def drive_status():
    """Get Google Drive configuration status."""
    return get_drive_status()


@app.post("/api/drive/upload")
async def drive_upload(
    request: DriveUploadRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Upload markdown content to Google Drive. Requires authentication.
    Returns file info including view link.
    """
    if not is_drive_configured():
        raise HTTPException(
            status_code=503,
            detail="Google Drive is not configured. Set GOOGLE_DRIVE_FOLDER_ID and add service account credentials."
        )

    try:
        result = upload_to_drive(
            filename=request.filename,
            content=request.content,
            mime_type='text/markdown'
        )
        return {
            "success": True,
            "file": result
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload to Google Drive: {str(e)}"
        )


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.getenv("PORT") or os.getenv("BACKEND_PORT") or "8001")
    uvicorn.run(app, host="0.0.0.0", port=port)
