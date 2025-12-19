"""OpenRouter API client for making LLM requests."""

import logging
import httpx
import asyncio
from typing import List, Dict, Any, Optional, Union
from . import config
from .config import DEFAULT_TIMEOUT, validate_openrouter_config

logger = logging.getLogger(__name__)

# Retry configuration for rate-limited requests (429 errors)
MAX_RETRIES = 2  # Reduced to avoid long delays
INITIAL_BACKOFF_SECONDS = 2.0  # Start with 2 second backoff
MAX_BACKOFF_SECONDS = 30.0  # Cap at 30 seconds


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
    retry_on_rate_limit: bool = True
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
    # Lazy validation - only check when actually making API calls
    validate_openrouter_config()

    if timeout is None:
        timeout = DEFAULT_TIMEOUT

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
    stage: str = None
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
    tasks = [query_model(model, messages, stage=stage) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}


async def query_models_streaming(
    models: List[str],
    messages: List[Dict[str, Any]]
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
