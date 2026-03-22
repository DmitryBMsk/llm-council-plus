"""Configuration for LLM-TTCC-TEAM-PRO."""

import os
from dotenv import load_dotenv

load_dotenv()

# Router type: 'openrouter' or 'ollama'
ROUTER_TYPE = os.getenv("ROUTER_TYPE", "openrouter").lower()

# OpenRouter settings
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = os.getenv(
    "OPENROUTER_API_URL",
    "https://openrouter.ai/api/v1/chat/completions"
)

# Ollama settings
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost:11434")

# Council members - list of model identifiers
# Parse from comma-separated string or use default
COUNCIL_MODELS_STR = os.getenv("COUNCIL_MODELS")
if COUNCIL_MODELS_STR:
    COUNCIL_MODELS = [model.strip() for model in COUNCIL_MODELS_STR.split(",")]
else:
    # Default models based on router type
    if ROUTER_TYPE == "ollama":
        COUNCIL_MODELS = [
            "deepseek-r1:latest",
            "llama3.1:latest",
            "qwen3:latest",
            "gemma3:latest",
        ]
    else:
        COUNCIL_MODELS = [
            "openai/gpt-5.1",
            "google/gemini-3-pro-preview",
            "anthropic/claude-sonnet-4.5",
            "x-ai/grok-4",
        ]

# Maximum council models (default 5, can be overridden via .env)
MAX_COUNCIL_MODELS = int(os.getenv("MAX_COUNCIL_MODELS", "5"))

# Minimum context length required for Chairman model (25K tokens)
MIN_CHAIRMAN_CONTEXT = int(os.getenv("MIN_CHAIRMAN_CONTEXT", "25000"))

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = os.getenv("CHAIRMAN_MODEL")
if not CHAIRMAN_MODEL:
    # Default chairman model based on router type
    if ROUTER_TYPE == "ollama":
        CHAIRMAN_MODEL = "gemma3:latest"
    else:
        CHAIRMAN_MODEL = "google/gemini-3-pro-preview"

# Data directory for conversation storage
DATA_DIR = os.getenv("DATA_DIR", "data/conversations")

# Timeout settings (in seconds)
DEFAULT_TIMEOUT = float(os.getenv("DEFAULT_TIMEOUT", "120.0"))
TITLE_GENERATION_TIMEOUT = float(os.getenv("TITLE_GENERATION_TIMEOUT", "180.0"))

# Storage backend configuration (Feature 2: Multi-Database Support)
DATABASE_TYPE = os.getenv("DATABASE_TYPE", "json").lower()
POSTGRESQL_URL = os.getenv("POSTGRESQL_URL", "")
MYSQL_URL = os.getenv("MYSQL_URL", "")

# Authentication configuration - default FALSE for easy open source setup
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"
JWT_SECRET = os.getenv("JWT_SECRET")
# User store (JSON string) for AUTH_ENABLED=true. Example: {"Alex":"pass","Bob":"pass"}.
AUTH_USERS = os.getenv("AUTH_USERS", "{}")

# Tools & Memory configuration (Feature 4)
ENABLE_TAVILY = os.getenv("ENABLE_TAVILY", "false").lower() == "true"
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
ENABLE_EXA = os.getenv("ENABLE_EXA", "false").lower() == "true"
EXA_API_KEY = os.getenv("EXA_API_KEY", "")
ENABLE_BRAVE = os.getenv("ENABLE_BRAVE", "false").lower() == "true"
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
ENABLE_OPENAI_EMBEDDINGS = os.getenv("ENABLE_OPENAI_EMBEDDINGS", "false").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ENABLE_MEMORY = os.getenv("ENABLE_MEMORY", "true").lower() == "true"
ENABLE_LANGGRAPH = os.getenv("ENABLE_LANGGRAPH", "false").lower() == "true"

# Google Drive settings
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "credentials/google-service-account.json"
)
GOOGLE_DRIVE_ENABLED = bool(GOOGLE_DRIVE_FOLDER_ID)

# Validate router type at import time (safe)
if ROUTER_TYPE not in ["openrouter", "ollama"]:
    raise ValueError(
        f"Invalid ROUTER_TYPE: {ROUTER_TYPE}. Must be 'openrouter' or 'ollama'"
    )


def validate_openrouter_config(router_type: str | None = None):
    """
    Validate OpenRouter configuration (called lazily when making API calls).

    Raises:
        ValueError: If using OpenRouter without API key
    """
    # Note: router selection can be per-conversation/request, so don't rely solely
    # on the module-global ROUTER_TYPE.
    rt = (router_type or ROUTER_TYPE or "openrouter").lower()
    if rt == "openrouter" and not OPENROUTER_API_KEY:
        raise ValueError(
            "OPENROUTER_API_KEY is required when ROUTER_TYPE=openrouter. "
            "Get your key at https://openrouter.ai/ or use ROUTER_TYPE=ollama for local models."
        )


def reload_config():
    """
    Reload configuration from .env file into memory.
    Call this after updating .env via setup wizard.

    Uses AppSettings.from_env() as the single source of truth, then
    projects the parsed values onto module globals for backward compat.
    """
    global ROUTER_TYPE, OPENROUTER_API_KEY, OPENROUTER_API_URL
    global OLLAMA_HOST, COUNCIL_MODELS, CHAIRMAN_MODEL
    global AUTH_ENABLED, JWT_SECRET, AUTH_USERS, ENABLE_TAVILY, TAVILY_API_KEY
    global ENABLE_EXA, EXA_API_KEY, ENABLE_BRAVE, BRAVE_API_KEY
    global ENABLE_OPENAI_EMBEDDINGS, OPENAI_API_KEY
    global ENABLE_MEMORY, ENABLE_LANGGRAPH
    global DATABASE_TYPE, POSTGRESQL_URL, MYSQL_URL
    global GOOGLE_DRIVE_FOLDER_ID, GOOGLE_SERVICE_ACCOUNT_FILE, GOOGLE_DRIVE_ENABLED
    global DATA_DIR, DEFAULT_TIMEOUT, TITLE_GENERATION_TIMEOUT
    global MAX_COUNCIL_MODELS, MIN_CHAIRMAN_CONTEXT

    # Reload .env file first so os.environ reflects disk state
    load_dotenv(override=True)

    # Parse all settings through the typed layer
    from .settings import AppSettings
    s = AppSettings.from_env()

    # Project typed settings onto module globals
    ROUTER_TYPE = s.router_type
    OPENROUTER_API_KEY = s.openrouter_api_key
    OPENROUTER_API_URL = s.openrouter_api_url
    OLLAMA_HOST = s.ollama_host
    COUNCIL_MODELS = list(s.council_models)
    CHAIRMAN_MODEL = s.chairman_model
    MAX_COUNCIL_MODELS = s.max_council_models
    MIN_CHAIRMAN_CONTEXT = s.min_chairman_context
    DEFAULT_TIMEOUT = s.default_timeout
    TITLE_GENERATION_TIMEOUT = s.title_generation_timeout
    DATA_DIR = s.data_dir
    DATABASE_TYPE = s.database_type
    POSTGRESQL_URL = s.postgresql_url
    MYSQL_URL = s.mysql_url
    AUTH_ENABLED = s.auth_enabled
    JWT_SECRET = s.jwt_secret
    AUTH_USERS = s.auth_users
    ENABLE_TAVILY = s.enable_tavily
    TAVILY_API_KEY = s.tavily_api_key
    ENABLE_EXA = s.enable_exa
    EXA_API_KEY = s.exa_api_key
    ENABLE_BRAVE = s.enable_brave
    BRAVE_API_KEY = s.brave_api_key
    ENABLE_OPENAI_EMBEDDINGS = s.enable_openai_embeddings
    OPENAI_API_KEY = s.openai_api_key
    ENABLE_MEMORY = s.enable_memory
    ENABLE_LANGGRAPH = s.enable_langgraph
    GOOGLE_DRIVE_FOLDER_ID = s.google_drive_folder_id
    GOOGLE_SERVICE_ACCOUNT_FILE = s.google_service_account_file
    GOOGLE_DRIVE_ENABLED = s.google_drive_enabled
