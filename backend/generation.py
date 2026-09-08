"""Validated generation budgets and provider completion diagnostics."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GenerationStage = Literal['stage1', 'stage2', 'stage3', 'title', 'continuation']
ReasoningEffort = Literal['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']


class GenerationLimits(BaseModel):
    model_config = ConfigDict(extra='forbid')
    max_tokens: int = Field(default=8192, ge=128, le=65536, strict=True)
    reasoning_max_tokens: int | None = Field(default=None, ge=1024, le=65535, strict=True)
    reasoning_effort: ReasoningEffort | None = None

    @model_validator(mode='after')
    def validate_reasoning(self):
        if self.reasoning_max_tokens is not None:
            if self.reasoning_effort is not None:
                raise ValueError('Set reasoning_max_tokens or reasoning_effort, not both')
            if self.reasoning_max_tokens >= self.max_tokens:
                raise ValueError('reasoning_max_tokens must be less than max_tokens')
        return self


def default_generation_limits():
    return {stage: GenerationLimits() for stage in ('stage1', 'stage2', 'stage3', 'title', 'continuation')}


def get_generation_limits(model: str, stage: str | None = None) -> GenerationLimits:
    from .runtime_settings import get_runtime_settings
    from .usage import _stage
    key = (stage or _stage.get() or 'stage1').lower()
    if key == 'stage3_fallback':
        key = 'stage3'
    settings = get_runtime_settings()
    overrides = settings.model_generation_limits.get(model, {})
    return overrides.get(key, settings.generation_limits.get(key, GenerationLimits()))


def completion_metadata(*, content, finish_reason, native_finish_reason=None,
                        generation_id=None, limits: GenerationLimits):
    """Token usage alone is never authoritative evidence of truncation."""
    truncated = (finish_reason in {'length', 'max_tokens'} or native_finish_reason in {'length', 'max_tokens'}) if (finish_reason or native_finish_reason) else None
    status = ('truncated' if content else 'truncated_empty') if truncated else (
        'completed' if finish_reason in {'stop', 'end_turn'} else 'unknown')
    return {'finish_reason': finish_reason, 'native_finish_reason': native_finish_reason,
            'generation_id': generation_id, 'truncated': truncated, 'completion_status': status,
            'effective_max_tokens': limits.max_tokens,
            'reasoning_max_tokens': limits.reasoning_max_tokens,
            'reasoning_effort': limits.reasoning_effort}
