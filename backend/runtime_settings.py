"""Runtime (non-secret) settings persisted to disk.

This module stores editable prompt templates, per-stage temperatures, and other non-secret runtime options.

Design goals:
- Safe to persist inside Docker volumes (`data/`).
- No API keys or secrets stored here.
- Backwards compatible: missing file -> defaults.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


SETTINGS_FILE = Path(
    os.getenv(
        "RUNTIME_SETTINGS_FILE",
        str(Path(__file__).parent.parent / "data" / "runtime_settings.json"),
    )
)


DEFAULT_STAGE1_PROMPT_TEMPLATE = "{full_query}"

DEFAULT_STAGE2_PROMPT_TEMPLATE = """You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Your task:
1. First, evaluate each response individually. For each response, explain what it does well and what it does poorly.
2. Then, at the very end of your response, provide a final ranking.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for your ENTIRE response:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...
Response C offers the most comprehensive answer...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""


DEFAULT_STAGE3_PROMPT_TEMPLATE = """You are the Chairman of an LLM-TTCC-TEAM-PRO council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

{rankings_block}{tools_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality (if available)
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""


class RuntimeSettings(BaseModel):
    """Non-secret runtime settings that users can edit in-app."""

    stage1_prompt_template: str = Field(default=DEFAULT_STAGE1_PROMPT_TEMPLATE)
    stage2_prompt_template: str = Field(default=DEFAULT_STAGE2_PROMPT_TEMPLATE)
    stage3_prompt_template: str = Field(default=DEFAULT_STAGE3_PROMPT_TEMPLATE)

    council_temperature: float = Field(default=0.5, ge=0.0, le=2.0)
    stage2_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    chairman_temperature: float = Field(default=0.4, ge=0.0, le=2.0)

    # Web search (non-secret). API keys stay in env / setup wizard.
    web_search_provider: str = Field(default="duckduckgo")  # off | duckduckgo | tavily | exa | brave
    web_max_results: int = Field(default=5, ge=1, le=10)
    web_full_content_results: int = Field(default=0, ge=0, le=10)  # Jina Reader fetches for top N


def default_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings()


def _read_json_file(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover
        logger.warning("Failed reading runtime settings file %s: %s", path, e)
        return None


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def get_runtime_settings() -> RuntimeSettings:
    """Load runtime settings from disk, returning defaults if missing/invalid."""
    raw = _read_json_file(SETTINGS_FILE)
    if not raw:
        return default_runtime_settings()
    try:
        return RuntimeSettings(**raw)
    except Exception as e:  # pragma: no cover
        logger.warning("Invalid runtime settings in %s, using defaults: %s", SETTINGS_FILE, e)
        return default_runtime_settings()


def save_runtime_settings(settings: RuntimeSettings) -> None:
    _atomic_write_json(SETTINGS_FILE, settings.model_dump())


def update_runtime_settings(**patch: Any) -> RuntimeSettings:
    """Apply a partial update and persist."""
    current = get_runtime_settings()
    merged = {**current.model_dump(), **patch}
    updated = RuntimeSettings(**merged)
    save_runtime_settings(updated)
    return updated


def reset_runtime_settings() -> RuntimeSettings:
    """Reset persisted settings back to defaults."""
    settings = default_runtime_settings()
    save_runtime_settings(settings)
    return settings
