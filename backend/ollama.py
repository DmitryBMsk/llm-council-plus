"""Ollama API client for making LLM requests."""

import logging
import httpx
from typing import List, Dict, Any, Optional
from .config import OLLAMA_HOST, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = None
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via Ollama API.

    Args:
        model: Ollama model identifier (e.g., "gemma3:latest")
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds (defaults to DEFAULT_TIMEOUT from config)

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    
    url = f"http://{OLLAMA_HOST}/api/chat"
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json=payload
            )
            response.raise_for_status()

            data = response.json()
            message = data['message']

            return {
                'content': message.get('content'),
                'reasoning_details': None  # Ollama API doesn't provide this
            }

    except httpx.ConnectError as e:
        logger.error("Connection error querying model %s: Cannot connect to Ollama at %s. Is Ollama running? Error: %s", model, OLLAMA_HOST, e)
        return None
    except httpx.HTTPStatusError as e:
        logger.error("HTTP error querying model %s: Status %s. Response: %s", model, e.response.status_code, e.response.text)
        return None
    except httpx.TimeoutException as e:
        logger.error("Timeout error querying model %s: Request took longer than %ss. Error: %s", model, timeout, e)
        return None
    except Exception as e:
        logger.error("Unexpected error querying model %s: %s: %s", model, type(e).__name__, e)
        return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]]
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of Ollama model identifiers
        messages: List of message dicts to send to each model

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    import asyncio

    # Create tasks for all models
    tasks = [query_model(model, messages) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}


async def query_models_streaming(
    models: List[str],
    messages: List[Dict[str, str]]
):
    """
    Query multiple models in parallel and yield results as they complete.

    Args:
        models: List of Ollama model identifiers
        messages: List of message dicts to send to each model

    Yields:
        Tuple of (model, response) as each model completes
    """
    import asyncio
    import time

    start_time = time.time()
    logger.debug("[PARALLEL] Starting %d model queries at t=0.0s", len(models))

    # Create named tasks so we can identify which model completed
    async def query_with_name(model: str):
        req_start = time.time() - start_time
        logger.debug("[PARALLEL] Starting request to %s at t=%.2fs", model, req_start)
        response = await query_model(model, messages)
        req_end = time.time() - start_time
        logger.debug("[PARALLEL] Got response from %s at t=%.2fs", model, req_end)
        return (model, response)

    # Create ALL tasks at once - they start executing immediately in parallel
    tasks = [asyncio.create_task(query_with_name(model)) for model in models]
    logger.debug("[PARALLEL] All %d tasks created and running in parallel", len(tasks))

    # Yield results as they complete (first finished = first yielded)
    for coro in asyncio.as_completed(tasks):
        model, response = await coro
        yield_time = time.time() - start_time
        logger.debug("[PARALLEL] Yielding %s at t=%.2fs", model, yield_time)
        yield (model, response)
