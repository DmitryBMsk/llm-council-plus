"""Router dispatch layer.

This module provides a single entrypoint for querying models while allowing the
caller to choose the router per request/conversation.

Supported router types:
- "openrouter"
- "ollama"

No fallback is implemented here; the selected router is authoritative.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from . import config
from . import openrouter, ollama

logger = logging.getLogger(__name__)

RouterType = str


def _normalize_router_type(router_type: Optional[str]) -> str:
    rt = (router_type or config.ROUTER_TYPE or "openrouter").lower()
    if rt not in {"openrouter", "ollama"}:
        raise ValueError(f"Invalid router_type: {router_type}")
    return rt


def build_message_content(
    router_type: Optional[str],
    text: str,
    images: Optional[List[Dict[str, str]]] = None,
) -> Union[str, List[Dict[str, Any]]]:
    rt = _normalize_router_type(router_type)
    if rt == "openrouter":
        return openrouter.build_message_content(text, images)

    # Ollama router: ignore images (text only).
    if images:
        logger.warning("Ignoring %d image(s) for Ollama router.", len(images))
    return text


async def query_model(
    router_type: Optional[str],
    *,
    model: str,
    messages: List[Dict[str, Any]],
    timeout: float | None = None,
    stage: str | None = None,
    retry_on_rate_limit: bool = True,
    temperature: float | None = None,
) -> Optional[Dict[str, Any]]:
    rt = _normalize_router_type(router_type)
    if rt == "openrouter":
        return await openrouter.query_model(
            model=model,
            messages=messages,
            timeout=timeout,
            stage=stage,
            retry_on_rate_limit=retry_on_rate_limit,
            temperature=temperature,
        )

    return await ollama.query_model(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        timeout=timeout,
        temperature=temperature,
    )


async def query_models_parallel(
    router_type: Optional[str],
    models: List[str],
    messages: List[Dict[str, Any]],
    *,
    stage: str | None = None,
    temperature: float | None = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    rt = _normalize_router_type(router_type)
    if rt == "openrouter":
        return await openrouter.query_models_parallel(
            models=models,
            messages=messages,
            stage=stage,
            temperature=temperature,
        )

    # Ollama router doesn't accept stage.
    return await ollama.query_models_parallel(
        models=models,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
    )


async def query_models_streaming(
    router_type: Optional[str],
    models: List[str],
    messages: List[Dict[str, Any]],
    *,
    temperature: float | None = None,
):
    rt = _normalize_router_type(router_type)
    if rt == "openrouter":
        async for item in openrouter.query_models_streaming(
            models=models,
            messages=messages,
            temperature=temperature,
        ):
            yield item
        return

    async for item in ollama.query_models_streaming(
        models=models,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
    ):
        yield item


async def query_models_with_stage_timeout(
    router_type: Optional[str],
    models: List[str],
    messages: List[Dict[str, Any]],
    *,
    stage: str | None = None,
    stage_timeout: float = 90.0,
    min_results: int = 3,
    temperature: float | None = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    rt = _normalize_router_type(router_type)
    if rt == "openrouter":
        return await openrouter.query_models_with_stage_timeout(
            models=models,
            messages=messages,
            stage=stage,
            stage_timeout=stage_timeout,
            min_results=min_results,
            temperature=temperature,
        )

    return await ollama.query_models_with_stage_timeout(
        models=models,
        messages=messages,  # type: ignore[arg-type]
        stage=stage,
        stage_timeout=stage_timeout,
        min_results=min_results,
        temperature=temperature,
    )

