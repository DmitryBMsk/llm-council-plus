"""OpenRouter API client for making LLM requests."""

import logging
import httpx
import asyncio
from typing import List, Dict, Any, Optional, Union
from . import config

logger = logging.getLogger(__name__)

# Retry configuration for rate-limited requests (429 errors)
MAX_RETRIES = 2  # Reduced to avoid long delays
INITIAL_BACKOFF_SECONDS = 2.0  # Start with 2 second backoff
MAX_BACKOFF_SECONDS = 30.0  # Cap at 30 seconds


def _require_openrouter_api_key() -> None:
    """
    Ensure OpenRouter is configured.

    Note: We validate the API key whenever this client is used, regardless of
    global ROUTER_TYPE, because router selection can be per-conversation/request.
    """
    if not (config.OPENROUTER_API_KEY or "").strip():
        raise ValueError(
            "OPENROUTER_API_KEY is required when using the OpenRouter router. "
            "Get your key at https://openrouter.ai/ or use ROUTER_TYPE=ollama for local models."
        )


def build_message_content(
    text: str,
    images: Optional[List[Dict[str, str]]] = None
) -> Union[str, List[Dict[str, Any]]]:
    """
    Build message content for OpenRouter API.

    For text-only messages, returns a string.
    For multimodal messages (with images), returns an array of content parts.

    Args:
        text: The text content of the message
        images: Optional list of image dicts with 'content' (base64 data URI) and 'filename'

    Returns:
        Either a string (text only) or a list of content parts (multimodal)
    """
    if not images:
        return text

    # Build multimodal content array
    content = [
        {"type": "text", "text": text}
    ]

    for image in images:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": image["content"]  # base64 data URI
            }
        })

    return content


async def query_model(
    model: str,
    messages: List[Dict[str, Any]],
    timeout: float = None,
    stage: str = None,
    retry_on_rate_limit: bool = True,
    temperature: float | None = None,
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via OpenRouter API with retry on rate limits.

    Args:
        model: OpenRouter model identifier (e.g., "openai/gpt-4o")
        messages: List of message dicts with 'role' and 'content'.
                  Content can be a string (text only) or an array of content parts
                  for multimodal messages (see build_message_content).
        timeout: Request timeout in seconds (defaults to DEFAULT_TIMEOUT from config)
        stage: Optional stage identifier for debugging (e.g., "STAGE1", "STAGE2", "STAGE3")
        retry_on_rate_limit: If True, retry on 429 errors with exponential backoff

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed

    Raises:
        ValueError: If OPENROUTER_API_KEY is not configured
    """
    # Lazy validation - only check when actually making API calls.
    _require_openrouter_api_key()

    if timeout is None:
        timeout = config.DEFAULT_TIMEOUT

    if stage:
        logger.debug("[%s] Querying model: %s", stage, model)

    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 8192,  # Limit to avoid credit issues
    }
    if temperature is not None:
        payload["temperature"] = temperature

    # Retry loop for rate limits
    retries = 0
    backoff = INITIAL_BACKOFF_SECONDS

    while True:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    config.OPENROUTER_API_URL,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()

                data = response.json()
                message = data['choices'][0]['message']

                return {
                    'content': message.get('content'),
                    'reasoning_details': message.get('reasoning_details')
                }

        except httpx.ConnectError as e:
            logger.error("Connection error querying model %s: Cannot connect to OpenRouter API. Error: %s", model, e)
            return {
                'error': True,
                'error_type': 'connection',
                'error_message': 'Cannot connect to OpenRouter API'
            }
        except httpx.HTTPStatusError as e:
            # Handle 429 rate limit with retry
            if e.response.status_code == 429 and retry_on_rate_limit and retries < MAX_RETRIES:
                retries += 1
                logger.warning("[%s] Rate limit (429) for model %s. Retry %d/%d in %.1fs...",
                             stage or "API", model, retries, MAX_RETRIES, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)  # Exponential backoff
                continue

            # Log non-retryable errors
            logger.error("HTTP error querying model %s: Status %s. Response: %s",
                        model, e.response.status_code, e.response.text[:500])

            # Parse error message from response
            error_msg = f"HTTP {e.response.status_code}"
            try:
                error_data = e.response.json()
                if 'error' in error_data and 'message' in error_data['error']:
                    error_msg = error_data['error']['message']
            except Exception:
                error_msg = e.response.text[:200] if e.response.text else error_msg

            if e.response.status_code == 401:
                return {
                    'error': True,
                    'error_type': 'auth',
                    'error_message': 'Invalid API key'
                }
            elif e.response.status_code == 404:
                return {
                    'error': True,
                    'error_type': 'not_found',
                    'error_message': error_msg or 'Model not available'
                }
            elif e.response.status_code == 429:
                return {
                    'error': True,
                    'error_type': 'rate_limit',
                    'error_message': f'Rate limited after {retries} retries'
                }
            else:
                return {
                    'error': True,
                    'error_type': 'http',
                    'error_message': error_msg
                }
        except httpx.TimeoutException as e:
            logger.error("Timeout error querying model %s: Request took longer than %ss. Error: %s", model, timeout, e)
            return {
                'error': True,
                'error_type': 'timeout',
                'error_message': f'Request timed out after {timeout}s'
            }
        except Exception as e:
            logger.error("Unexpected error querying model %s: %s: %s", model, type(e).__name__, e)
            return {
                'error': True,
                'error_type': 'unknown',
                'error_message': str(e)
            }


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, Any]],
    stage: str = None,
    temperature: float | None = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of OpenRouter model identifiers
        messages: List of message dicts to send to each model
        stage: Optional stage identifier for debugging (e.g., "STAGE1", "STAGE2")

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    import asyncio

    if stage:
        logger.debug("[%s] Querying %d models in parallel...", stage, len(models))

    # Create tasks for all models
    tasks = [query_model(model, messages, stage=stage, temperature=temperature) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}


async def query_models_streaming(
    models: List[str],
    messages: List[Dict[str, Any]],
    temperature: float | None = None,
):
    """
    Query multiple models in parallel and yield results as they complete.

    Args:
        models: List of OpenRouter model identifiers
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
        response = await query_model(model, messages, temperature=temperature)
        req_end = time.time() - start_time
        logger.debug("[PARALLEL] Got response from %s at t=%.2fs", model, req_end)
        return (model, response)

    # Create ALL tasks at once - they start executing immediately in parallel
    tasks = [asyncio.create_task(query_with_name(model)) for model in models]
    logger.debug("[PARALLEL] All %d tasks created and running in parallel", len(tasks))

    try:
        # Yield results as they complete (first finished = first yielded)
        for coro in asyncio.as_completed(tasks):
            model, response = await coro
            yield_time = time.time() - start_time
            logger.debug("[PARALLEL] Yielding %s at t=%.2fs", model, yield_time)
            yield (model, response)
    finally:
        # If the consumer disconnects/cancels mid-stream, ensure we don't leak background tasks.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def query_models_with_stage_timeout(
    models: List[str],
    messages: List[Dict[str, Any]],
    stage: str = None,
    stage_timeout: float = 90.0,
    min_results: int = 3,
    temperature: float | None = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel with overall stage timeout.

    Uses first-N-complete pattern: returns when either:
    - All models complete
    - stage_timeout is reached (returns completed results)
    - min_results are collected AND timeout reached

    This prevents slow models from blocking the entire stage.

    Args:
        models: List of OpenRouter model identifiers
        messages: List of message dicts to send to each model
        stage: Optional stage identifier for debugging
        stage_timeout: Maximum time to wait for this stage (seconds)
        min_results: Minimum number of results to wait for before timeout applies

    Returns:
        Dict mapping model identifier to response dict
    """
    import asyncio
    import time

    start_time = time.time()
    results = {}

    if stage:
        logger.info("[%s] Starting with stage_timeout=%.1fs, min_results=%d",
                   stage, stage_timeout, min_results)

    # Create named tasks
    async def query_with_name(model: str):
        response = await query_model(model, messages, stage=stage, temperature=temperature)
        return (model, response)

    # Create ALL tasks at once
    tasks = {asyncio.create_task(query_with_name(model)): model for model in models}
    pending = set(tasks.keys())

    extended_wait_used = False  # Track if we've already done the extended wait

    while pending:
        elapsed = time.time() - start_time
        remaining_timeout = stage_timeout - elapsed

        # Check if we should stop waiting
        if remaining_timeout <= 0:
            if len(results) >= min_results:
                logger.warning("[%s] Stage timeout reached after %.1fs with %d/%d results, proceeding",
                             stage, elapsed, len(results), len(models))
                # Cancel remaining tasks
                for task in pending:
                    task.cancel()
                break
            elif not extended_wait_used:
                # Not enough results, wait a bit more (up to 30s extra) - but only once
                extended_wait_used = True
                remaining_timeout = min(30.0, stage_timeout * 0.5)
                logger.warning("[%s] Only %d results after timeout, waiting %.1fs more for min_results=%d",
                             stage, len(results), remaining_timeout, min_results)
            else:
                # Extended wait already used, give up and return what we have
                logger.warning("[%s] Extended wait exhausted after %.1fs with only %d/%d results, proceeding anyway",
                             stage, elapsed, len(results), len(models))
                for task in pending:
                    task.cancel()
                break

        try:
            # Wait for next task to complete
            done, pending = await asyncio.wait(
                pending,
                timeout=remaining_timeout,
                return_when=asyncio.FIRST_COMPLETED
            )

            for task in done:
                try:
                    model, response = task.result()
                    results[model] = response
                    logger.debug("[%s] Got result from %s at t=%.2fs (%d/%d)",
                               stage, model, time.time() - start_time, len(results), len(models))
                except Exception as e:
                    model = tasks[task]
                    logger.error("[%s] Task for %s failed: %s", stage, model, e)
                    results[model] = {
                        'error': True,
                        'error_type': 'unknown',
                        'error_message': str(e)
                    }

            if not done and not pending:
                break

        except asyncio.TimeoutError:
            # Timeout waiting for next result
            if len(results) >= min_results:
                logger.warning("[%s] Timeout with %d/%d results, proceeding",
                             stage, len(results), len(models))
                for task in pending:
                    task.cancel()
                break

    # Add timeout entries for models that didn't complete
    completed_models = set(results.keys())
    for model in models:
        if model not in completed_models:
            results[model] = {
                'error': True,
                'error_type': 'stage_timeout',
                'error_message': f'Model did not respond within stage timeout ({stage_timeout}s)'
            }
            logger.warning("[%s] Model %s timed out at stage level", stage, model)

    total_time = time.time() - start_time
    success_count = sum(1 for r in results.values() if r and not r.get('error'))
    logger.info("[%s] Completed in %.2fs: %d success, %d failed/timeout",
               stage, total_time, success_count, len(models) - success_count)

    return results
