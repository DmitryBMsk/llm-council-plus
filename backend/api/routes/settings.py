"""Runtime settings endpoints — /api/settings/*."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

from ..deps import get_current_user
from ...runtime_settings import (
    RuntimeSettings,
    get_runtime_settings,
    update_runtime_settings,
    reset_runtime_settings,
    default_runtime_settings,
    save_runtime_settings,
)

router = APIRouter(tags=["settings"])


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


@router.get("/api/settings")
async def get_settings_endpoint(current_user: str = Depends(get_current_user)):
    """Get runtime settings (prompt templates + temperatures)."""
    return get_runtime_settings().model_dump()


@router.patch("/api/settings")
async def update_settings_endpoint(
    request: UpdateRuntimeSettingsRequest,
    current_user: str = Depends(get_current_user),
):
    """Patch runtime settings (non-secret)."""
    patch = {k: v for k, v in request.model_dump().items() if v is not None}
    updated = update_runtime_settings(**patch) if patch else get_runtime_settings()
    return updated.model_dump()


@router.get("/api/settings/defaults")
async def get_settings_defaults_endpoint(current_user: str = Depends(get_current_user)):
    """Get default runtime settings."""
    return default_runtime_settings().model_dump()


@router.post("/api/settings/reset")
async def reset_settings_endpoint(current_user: str = Depends(get_current_user)):
    """Reset runtime settings to defaults."""
    return reset_runtime_settings().model_dump()


@router.get("/api/settings/export")
async def export_settings_endpoint(current_user: str = Depends(get_current_user)):
    """Export runtime settings as JSON (same shape as GET /api/settings)."""
    return get_runtime_settings().model_dump()


@router.post("/api/settings/import")
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
