"""
TOON (Token-Oriented Object Notation) encoder for LLM token optimization.

This module provides functions to:
1. Convert Python data structures to TOON format
2. Count tokens using tiktoken
3. Calculate token savings statistics
"""

import json
import logging
from typing import Any

try:
    from toon import encode as toon_encode, decode as toon_decode
    TOON_AVAILABLE = True
except ImportError:
    TOON_AVAILABLE = False
    logging.warning("python-toon not installed. TOON encoding disabled.")

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logging.warning("tiktoken not installed. Token counting disabled.")

logger = logging.getLogger(__name__)


def encode_for_llm(data: dict | list) -> str:
    """
    Convert Python data to TOON format for LLM consumption.

    Falls back to JSON if TOON is not available.

    Args:
        data: Python dict or list to encode

    Returns:
        TOON-formatted string (or JSON if TOON unavailable)
    """
    if not TOON_AVAILABLE:
        logger.info("[TOON] Not available, using JSON fallback")
        return json.dumps(data, ensure_ascii=False)

    try:
        result = toon_encode(data)
        logger.info(f"[TOON] Encoded {len(data) if isinstance(data, list) else 1} items, {len(result)} chars")
        return result
    except Exception as e:
        logger.warning(f"TOON encoding failed, falling back to JSON: {e}")
        return json.dumps(data, ensure_ascii=False)


def decode_toon(toon_str: str) -> dict | list:
    """
    Decode TOON string back to Python data.

    Args:
        toon_str: TOON-formatted string

    Returns:
        Python dict or list
    """
    if not TOON_AVAILABLE:
        return json.loads(toon_str)

    try:
        return toon_decode(toon_str)
    except Exception as e:
        logger.warning(f"TOON decoding failed, trying JSON: {e}")
        return json.loads(toon_str)


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Count tokens in text using tiktoken.

    Args:
        text: Text to count tokens for
        model: Model name for tokenizer selection

    Returns:
        Number of tokens (or estimated count if tiktoken unavailable)
    """
    if not TIKTOKEN_AVAILABLE:
        # Rough estimate: ~4 characters per token
        return len(text) // 4

    try:
        # Try to get encoding for specific model
        try:
            enc = tiktoken.encoding_for_model(model)
        except KeyError:
            # Fall back to cl100k_base (used by GPT-4, Claude, etc.)
            enc = tiktoken.get_encoding("cl100k_base")

        return len(enc.encode(text))
    except Exception as e:
        logger.warning(f"Token counting failed: {e}")
        return len(text) // 4


def get_savings_stats(original_data: dict | list, toon_text: str | None = None) -> dict:
    """
    Calculate token savings statistics for TOON vs JSON.

    Args:
        original_data: Original Python data structure
        toon_text: Pre-encoded TOON text (optional, will encode if not provided)

    Returns:
        Dict with json_tokens, toon_tokens, saved_percent
    """
    # Get JSON representation
    json_text = json.dumps(original_data, ensure_ascii=False)
    json_tokens = count_tokens(json_text)

    # Get TOON representation
    if toon_text is None:
        toon_text = encode_for_llm(original_data)
    toon_tokens = count_tokens(toon_text)

    # Calculate savings
    if json_tokens > 0:
        saved_percent = ((json_tokens - toon_tokens) / json_tokens) * 100
    else:
        saved_percent = 0.0

    stats = {
        "json_tokens": json_tokens,
        "toon_tokens": toon_tokens,
        "saved_percent": round(saved_percent, 1)
    }
    logger.info(f"[TOON] Stats: {json_tokens} JSON → {toon_tokens} TOON ({stats['saved_percent']}% saved)")
    return stats


def format_conversation_history(messages: list[dict]) -> str:
    """
    Format conversation history for LLM context using TOON.

    Args:
        messages: List of message dicts with 'role' and 'content'

    Returns:
        TOON-formatted conversation history
    """
    # Simplify messages for TOON encoding
    simplified = [
        {"role": msg.get("role", "user"), "content": msg.get("content", "")}
        for msg in messages
    ]

    return encode_for_llm(simplified)


def format_stage1_responses(responses: list[dict]) -> str:
    """
    Format Stage 1 responses for Stage 2 peer review using TOON.

    Args:
        responses: List of response dicts with 'model' and 'response'

    Returns:
        TOON-formatted responses
    """
    # Simplify for TOON - just the essential fields
    simplified = [
        {"model": resp.get("model", "unknown"), "response": resp.get("response", "")}
        for resp in responses
    ]

    return encode_for_llm(simplified)


def format_rankings(rankings: list[dict]) -> str:
    """
    Format Stage 2 rankings for Stage 3 chairman using TOON.

    Args:
        rankings: List of ranking dicts

    Returns:
        TOON-formatted rankings
    """
    # Simplify for TOON
    simplified = [
        {
            "model": rank.get("model", "unknown"),
            "ranking": rank.get("ranking", ""),
            "parsed_ranking": rank.get("parsed_ranking", [])
        }
        for rank in rankings
    ]

    return encode_for_llm(simplified)


def aggregate_token_stats(*stage_stats: dict) -> dict:
    """
    Aggregate token statistics from multiple stages.

    Args:
        *stage_stats: Variable number of stage stat dicts

    Returns:
        Aggregated totals
    """
    total_json = sum(s.get("json_tokens", 0) for s in stage_stats)
    total_toon = sum(s.get("toon_tokens", 0) for s in stage_stats)

    if total_json > 0:
        saved_percent = ((total_json - total_toon) / total_json) * 100
    else:
        saved_percent = 0.0

    return {
        "json_tokens": total_json,
        "toon_tokens": total_toon,
        "saved_percent": round(saved_percent, 1)
    }


# Check if TOON is working
def is_toon_available() -> bool:
    """Check if TOON encoding is available."""
    return TOON_AVAILABLE


def is_token_counting_available() -> bool:
    """Check if token counting is available."""
    return TIKTOKEN_AVAILABLE
