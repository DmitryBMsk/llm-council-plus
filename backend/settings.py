"""Typed application settings with explicit reload boundaries.

Provides a single source of truth for environment-derived configuration.
Classifies each setting as hot-reloadable or restart-required.

Usage:
    from backend.settings import AppSettings
    settings = AppSettings.from_env()

The existing config.py module globals remain as the primary access path
for consumers. This module provides the typed parsing layer underneath.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional


# Settings that can be changed at runtime via setup wizard reload
HOT_RELOADABLE: frozenset[str] = frozenset({
    "router_type",
    "openrouter_api_key",
    "openrouter_api_url",
    "ollama_host",
    "council_models",
    "chairman_model",
    "max_council_models",
    "min_chairman_context",
    "default_timeout",
    "title_generation_timeout",
    "auth_enabled",
    "jwt_secret",
    "auth_users",
    "enable_tavily",
    "tavily_api_key",
    "enable_exa",
    "exa_api_key",
    "enable_brave",
    "brave_api_key",
    "enable_openai_embeddings",
    "openai_api_key",
    "enable_memory",
    "enable_langgraph",
    "google_drive_folder_id",
    "google_service_account_file",
    "data_dir",
})

# Settings that require a container/process restart to take effect
RESTART_REQUIRED: frozenset[str] = frozenset({
    "database_type",
    "postgresql_url",
    "mysql_url",
})


def _parse_bool(value: str, default: bool = False) -> bool:
    return value.strip().lower() == "true" if value else default


def _parse_council_models(models_str: Optional[str], router_type: str) -> List[str]:
    if models_str:
        return [m.strip() for m in models_str.split(",") if m.strip()]
    if router_type == "ollama":
        return ["deepseek-r1:latest", "llama3.1:latest", "qwen3:latest", "gemma3:latest"]
    return [
        "openai/gpt-5.5",
        "google/gemini-3.1-pro-preview",
        "anthropic/claude-sonnet-5",
        "x-ai/grok-4.3",
    ]


def _parse_chairman(chairman_str: Optional[str], router_type: str) -> str:
    if chairman_str:
        return chairman_str
    return "gemma3:latest" if router_type == "ollama" else "google/gemini-3.1-pro-preview"


@dataclass(frozen=True)
class AppSettings:
    """Immutable snapshot of application configuration parsed from environment."""

    # Router
    router_type: str = "openrouter"
    openrouter_api_key: Optional[str] = None
    openrouter_api_url: str = "https://openrouter.ai/api/v1/chat/completions"
    ollama_host: str = "localhost:11434"

    # Council
    council_models: List[str] = field(default_factory=list)
    chairman_model: str = "google/gemini-3.1-pro-preview"
    max_council_models: int = 5
    min_chairman_context: int = 25000

    # Timeouts
    default_timeout: float = 120.0
    title_generation_timeout: float = 180.0

    # Storage
    data_dir: str = "data/conversations"
    database_type: str = "json"
    postgresql_url: str = ""
    mysql_url: str = ""

    # Auth
    auth_enabled: bool = False
    jwt_secret: Optional[str] = None
    auth_users: str = "{}"

    # Search providers
    enable_tavily: bool = False
    tavily_api_key: str = ""
    enable_exa: bool = False
    exa_api_key: str = ""
    enable_brave: bool = False
    brave_api_key: str = ""

    # Embeddings & features
    enable_openai_embeddings: bool = False
    openai_api_key: str = ""
    enable_memory: bool = True
    enable_langgraph: bool = False

    # Google Drive
    google_drive_folder_id: Optional[str] = None
    google_service_account_file: str = "credentials/google-service-account.json"

    @classmethod
    def from_env(cls) -> AppSettings:
        """Parse all settings from current os.environ / .env state."""
        router_type = os.getenv("ROUTER_TYPE", "openrouter").lower()
        council_models_str = os.getenv("COUNCIL_MODELS")

        return cls(
            router_type=router_type,
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
            openrouter_api_url=os.getenv(
                "OPENROUTER_API_URL",
                "https://openrouter.ai/api/v1/chat/completions",
            ),
            ollama_host=os.getenv("OLLAMA_HOST", "localhost:11434"),
            council_models=_parse_council_models(council_models_str, router_type),
            chairman_model=_parse_chairman(os.getenv("CHAIRMAN_MODEL"), router_type),
            max_council_models=int(os.getenv("MAX_COUNCIL_MODELS", "5")),
            min_chairman_context=int(os.getenv("MIN_CHAIRMAN_CONTEXT", "25000")),
            default_timeout=float(os.getenv("DEFAULT_TIMEOUT", "120.0")),
            title_generation_timeout=float(os.getenv("TITLE_GENERATION_TIMEOUT", "180.0")),
            data_dir=os.getenv("DATA_DIR", "data/conversations"),
            database_type=os.getenv("DATABASE_TYPE", "json").lower(),
            postgresql_url=os.getenv("POSTGRESQL_URL", ""),
            mysql_url=os.getenv("MYSQL_URL", ""),
            auth_enabled=_parse_bool(os.getenv("AUTH_ENABLED", "false")),
            jwt_secret=os.getenv("JWT_SECRET"),
            auth_users=os.getenv("AUTH_USERS", "{}"),
            enable_tavily=_parse_bool(os.getenv("ENABLE_TAVILY", "false")),
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
            enable_exa=_parse_bool(os.getenv("ENABLE_EXA", "false")),
            exa_api_key=os.getenv("EXA_API_KEY", ""),
            enable_brave=_parse_bool(os.getenv("ENABLE_BRAVE", "false")),
            brave_api_key=os.getenv("BRAVE_API_KEY", ""),
            enable_openai_embeddings=_parse_bool(os.getenv("ENABLE_OPENAI_EMBEDDINGS", "false")),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            enable_memory=_parse_bool(os.getenv("ENABLE_MEMORY", "true"), default=True),
            enable_langgraph=_parse_bool(os.getenv("ENABLE_LANGGRAPH", "false")),
            google_drive_folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID"),
            google_service_account_file=os.getenv(
                "GOOGLE_SERVICE_ACCOUNT_FILE",
                "credentials/google-service-account.json",
            ),
        )

    @property
    def google_drive_enabled(self) -> bool:
        return bool(self.google_drive_folder_id)
