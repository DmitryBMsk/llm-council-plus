"""Ollama API client for making LLM requests."""

import logging
import httpx
from typing import List, Dict, Any, Union, TypedDict, Literal
from . import config

logger = logging.getLogger(__name__)

# Error type literals for better type checking
ErrorType = Literal['connection', 'not_found', 'http', 'timeout', 'unknown', 'stage_timeout']


class SuccessResponse(TypedDict, total=False):
    """Successful response from Ollama."""
    content: str
    reasoning_details: Any


class ErrorResponse(TypedDict):
    """Error response matching OpenRouter format."""
    error: bool  # Always True
    error_type: ErrorType
    error_message: str


# Union type for query_model return
QueryResponse = Union[SuccessResponse, ErrorResponse]


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = None,
    temperature: float | None = None,
) -> QueryResponse:
    """
    Query a single model via Ollama API.

    Args:
        model: Ollama model identifier (e.g., "gemma3:latest")
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds (defaults to DEFAULT_TIMEOUT from config)
        temperature: Optional temperature for response generation

    Returns:
        On success: dict with 'content' (str) and optional 'reasoning_details'
        On error: dict with 'error' (True), 'error_type', and 'error_message'

        Error types: 'connection', 'not_found', 'http', 'timeout', 'unknown'
    """
    if timeout is None:
        timeout = config.DEFAULT_TIMEOUT
    
    url = f"http://{config.OLLAMA_HOST}/api/chat"
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if temperature is not None:
        payload["options"] = {"temperature": temperature}

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
        logger.error("Connection error querying model %s: Cannot connect to Ollama at %s. Is Ollama running? Error: %s", model, config.OLLAMA_HOST, e)
        return {
            'error': True,
            'error_type': 'connection',
            'error_message': f'Cannot connect to Ollama at {config.OLLAMA_HOST}. Is Ollama running?'
        }
    except httpx.HTTPStatusError as e:
        logger.error("HTTP error querying model %s: Status %s. Response: %s", model, e.response.status_code, e.response.text)
        error_msg = f"HTTP {e.response.status_code}"
        if e.response.status_code == 404:
            return {
                'error': True,
                'error_type': 'not_found',
                'error_message': f'Model {model} not found. Try: ollama pull {model}'
            }
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
    messages: List[Dict[str, str]],
    temperature: float | None = None,
) -> Dict[str, QueryResponse]:
    """
    Query multiple models in parallel.

    Args:
        models: List of Ollama model identifiers
        messages: List of message dicts to send to each model
        temperature: Optional temperature for response generation

    Returns:
        Dict mapping model identifier to QueryResponse (success or error dict)
    """
    import asyncio

    # Create tasks for all models
    tasks = [query_model(model, messages, temperature=temperature) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}


async def query_models_streaming(
    models: List[str],
    messages: List[Dict[str, str]],
    temperature: float | None = None,
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
    messages: List[Dict[str, str]],
    stage: str = None,
    stage_timeout: float = 90.0,
    min_results: int = 3,
    temperature: float | None = None,
) -> Dict[str, QueryResponse]:
    """
    Query multiple models in parallel with overall stage timeout.

    Uses first-N-complete pattern: returns when either:
    - All models complete
    - stage_timeout is reached (returns completed results)
    - min_results are collected AND timeout reached

    Args:
        models: List of Ollama model identifiers
        messages: List of message dicts to send to each model
        stage: Optional stage identifier for debugging
        stage_timeout: Maximum time to wait for this stage (seconds)
        min_results: Minimum number of results to wait for before timeout applies
        temperature: Optional temperature for response generation

    Returns:
        Dict mapping model identifier to QueryResponse (success or error dict)
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
        response = await query_model(model, messages, temperature=temperature)
        return (model, response)

    # Create ALL tasks at once
    tasks = {asyncio.create_task(query_with_name(model)): model for model in models}
    all_tasks = list(tasks.keys())
    pending = set(all_tasks)
    extended_wait_used = False  # Track if we've already done the extended wait

    try:
        while pending:
            elapsed = time.time() - start_time
            remaining_timeout = stage_timeout - elapsed

            if remaining_timeout <= 0:
                if len(results) >= min_results:
                    logger.warning("[%s] Stage timeout reached after %.1fs with %d/%d results",
                                 stage, elapsed, len(results), len(models))
                    for task in pending:
                        task.cancel()
                    break
                elif not extended_wait_used:
                    # Not enough results, wait a bit more (up to 30s extra) - but only once
                    extended_wait_used = True
                    remaining_timeout = min(30.0, stage_timeout * 0.5)
                    logger.warning("[%s] Only %d results, waiting %.1fs more",
                                 stage, len(results), remaining_timeout)
                else:
                    # Extended wait already used, give up and return what we have
                    logger.warning("[%s] Extended wait exhausted after %.1fs with only %d/%d results, proceeding anyway",
                                 stage, elapsed, len(results), len(models))
                    for task in pending:
                        task.cancel()
                    break

            try:
                done, pending = await asyncio.wait(
                    pending,
                    timeout=remaining_timeout,
                    return_when=asyncio.FIRST_COMPLETED
                )

                for task in done:
                    try:
                        model, response = task.result()
                        results[model] = response
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
                if len(results) >= min_results:
                    logger.warning("[%s] Timeout with %d/%d results, proceeding",
                                 stage, len(results), len(models))
                    for task in pending:
                        task.cancel()
                    break
    finally:
        # Make cancellation deterministic and avoid leaking background tasks.
        for task in all_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*all_tasks, return_exceptions=True)

    # Add timeout entries for missing models
    for model in models:
        if model not in results:
            results[model] = {
                'error': True,
                'error_type': 'stage_timeout',
                'error_message': f'Model did not respond within stage timeout ({stage_timeout}s)'
            }

    total_time = time.time() - start_time
    success_count = sum(1 for r in results.values() if r and not r.get('error'))
    logger.info("[%s] Completed in %.2fs: %d success, %d failed",
               stage, total_time, success_count, len(models) - success_count)

    return results
