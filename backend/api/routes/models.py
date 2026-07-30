"""Models endpoint — /api/models with caching."""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
import asyncio
import logging
import time
import httpx

from ... import config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])

# Cache for models per router_type (5 minute TTL)
# Shape: { "openrouter": {"data": {...}, "timestamp": 123}, "ollama": {...} }
_models_cache: Dict[str, Dict[str, Any]] = {}
_models_cache_lock: Optional[asyncio.Lock] = None  # Initialized lazily for event-loop safety
_MODELS_CACHE_TTL = 300  # 5 minutes


def _get_models_cache_lock() -> asyncio.Lock:
    """Get or create the models cache lock (lazy init for event-loop safety)."""
    global _models_cache_lock
    if _models_cache_lock is None:
        _models_cache_lock = asyncio.Lock()
    return _models_cache_lock


def _parse_price(price_str: str) -> float:
    """Parse price string to float (per million tokens)."""
    try:
        # Price is per token, convert to per million
        price_per_token = float(price_str)
        return price_per_token * 1_000_000
    except (ValueError, TypeError):
        return 0.0


def _format_price(price_per_million: float) -> str:
    """Format price per million tokens as human-readable string."""
    if price_per_million == 0:
        return "FREE"
    elif price_per_million < 0.01:
        return f"${price_per_million:.4f}/M"
    elif price_per_million < 1:
        return f"${price_per_million:.2f}/M"
    else:
        return f"${price_per_million:.0f}/M"


def _format_context(context_length: int) -> str:
    """Format context length as human-readable string."""
    if context_length >= 1_000_000:
        return f"{context_length / 1_000_000:.1f}M"
    elif context_length >= 1000:
        return f"{context_length // 1000}K"
    else:
        return str(context_length)


def _get_tier(input_price: float, output_price: float, is_free: bool) -> str:
    """Determine pricing tier based on output price."""
    if is_free:
        return "free"
    # Based on output price per million tokens
    if output_price >= 10:
        return "premium"
    elif output_price >= 1:
        return "standard"
    else:
        return "budget"


def _extract_provider(model_id: str, model_name: str) -> str:
    """Extract provider name from model ID or name."""
    # Try to get from ID (format: provider/model-name)
    if "/" in model_id:
        provider_slug = model_id.split("/")[0]
        # Map common slugs to proper names
        provider_map = {
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "google": "Google",
            "meta-llama": "Meta",
            "mistralai": "Mistral",
            "cohere": "Cohere",
            "x-ai": "xAI",
            "deepseek": "DeepSeek",
            "nvidia": "NVIDIA",
            "amazon": "Amazon",
            "microsoft": "Microsoft",
            "qwen": "Alibaba",
            "perplexity": "Perplexity",
            "01-ai": "01.AI",
            "databricks": "Databricks",
            "allenai": "AllenAI",
            "tngtech": "TNG Tech",
            "moonshotai": "MoonshotAI",
            "z-ai": "Z.AI",
        }
        return provider_map.get(provider_slug, provider_slug.title())

    # Fallback: extract from model name
    if ":" in model_name:
        return model_name.split(":")[0].strip()
    return "Unknown"


@router.get("/api/models")
async def get_available_models(router_type: Optional[str] = None):
    """
    Get available models from OpenRouter or Ollama.
    Returns formatted model list with pricing and capabilities.
    Cached for 5 minutes to reduce API calls.
    """
    effective_router_type = (router_type or config.ROUTER_TYPE or "openrouter").lower()
    if effective_router_type not in {"openrouter", "ollama"}:
        raise HTTPException(status_code=400, detail="Invalid router_type. Must be 'openrouter' or 'ollama'.")

    # Check cache with lock for thread safety
    async with _get_models_cache_lock():
        cache_entry = _models_cache.get(effective_router_type)
        if cache_entry and cache_entry.get("data") and (time.time() - cache_entry.get("timestamp", 0)) < _MODELS_CACHE_TTL:
            return cache_entry["data"]

    if effective_router_type == "ollama":
        # Fetch from Ollama local API
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://{config.OLLAMA_HOST}/api/tags", timeout=10.0)
                if response.status_code != 200:
                    raise HTTPException(status_code=503, detail="Failed to fetch Ollama models")

                data = response.json()
                models = []
                for model in data.get("models", []):
                    # Skip embedding-only models — they don't support chat
                    model_name_lower = model["name"].lower()
                    if "embed" in model_name_lower or "/bge-" in model_name_lower:
                        continue
                    models.append({
                        "id": model["name"],
                        "name": model["name"],
                        "provider": "Ollama (Local)",
                        "context": "N/A",
                        "contextLength": config.MIN_CHAIRMAN_CONTEXT,
                        "inputPrice": "FREE",
                        "outputPrice": "FREE",
                        "tier": "free",
                        "isFree": True,
                        "description": f"Local model: {model.get('details', {}).get('family', 'Unknown')}",
                        "modality": "text->text",
                    })

                result = {"models": models, "router_type": "ollama", "max_models": config.MAX_COUNCIL_MODELS}
                async with _get_models_cache_lock():
                    _models_cache[effective_router_type] = {"data": result, "timestamp": time.time()}
                return result

        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Cannot connect to Ollama: {str(e)}")

    else:
        # Fetch from OpenRouter API
        if not config.OPENROUTER_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="OpenRouter API key not configured. Complete setup first."
            )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
                    timeout=30.0
                )

                if response.status_code != 200:
                    raise HTTPException(
                        status_code=503,
                        detail=f"OpenRouter API error: {response.status_code}"
                    )

                data = response.json()
                models = []

                for model in data.get("data", []):
                    model_id = model.get("id", "")
                    model_name = model.get("name", model_id)

                    # Parse pricing
                    pricing = model.get("pricing", {})
                    input_price = _parse_price(pricing.get("prompt", "0"))
                    output_price = _parse_price(pricing.get("completion", "0"))
                    is_free = input_price == 0 and output_price == 0

                    # Get context length
                    context_length = model.get("context_length", 0)
                    top_provider = model.get("top_provider", {})
                    if top_provider.get("context_length"):
                        context_length = top_provider["context_length"]

                    # Get modality
                    arch = model.get("architecture", {})
                    modality = arch.get("modality", "text->text")
                    input_modalities = arch.get("input_modalities", ["text"])

                    models.append({
                        "id": model_id,
                        "name": model_name,
                        "provider": _extract_provider(model_id, model_name),
                        "context": _format_context(context_length),
                        "contextLength": context_length,
                        "inputPrice": _format_price(input_price),
                        "outputPrice": _format_price(output_price),
                        "inputPriceRaw": input_price,
                        "outputPriceRaw": output_price,
                        "tier": _get_tier(input_price, output_price, is_free),
                        "isFree": is_free,
                        "description": model.get("description", "")[:200],  # Truncate long descriptions
                        "modality": modality,
                        "supportsImages": "image" in input_modalities,
                        "supportsAudio": "audio" in input_modalities,
                    })

                # Sort by output price (cheapest first), then by name
                models.sort(key=lambda m: (m["outputPriceRaw"], m["name"]))

                result = {"models": models, "router_type": "openrouter", "count": len(models), "max_models": config.MAX_COUNCIL_MODELS}
                async with _get_models_cache_lock():
                    _models_cache[effective_router_type] = {"data": result, "timestamp": time.time()}
                return result

        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Failed to fetch models: {str(e)}")


# --- Curated free-model preset (https://shir-man.com/free-llm/) -------------
# Daily-ranked list of free OpenRouter models (health checks + lite agent
# evals). Used by the frontend "Free" preset; falls back to the plain
# free-tier filter when this feed is unavailable.

FREE_LLM_RECOMMENDATION_URL = "https://shir-man-com.pages.dev/api/free-llm/recommendation"
_FREE_PRESET_CACHE_TTL = 3600  # feed updates daily; 1h keeps us fresh enough
_free_preset_cache: Dict[str, Any] = {"data": None, "timestamp": 0.0}


def _extract_free_preset(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract ranked free model ids (primary first) from the recommendation feed."""
    ids = []
    primary = (data.get("primary") or {}).get("id")
    if primary:
        ids.append(primary)
    for alt in data.get("alternatives") or []:
        alt_id = alt.get("id")
        if alt_id and alt_id not in ids:
            ids.append(alt_id)
    return {
        "models": ids,
        "chairman": primary,
        "updated_at": data.get("updatedAt"),
        "source": "https://shir-man.com/free-llm/",
    }


async def _fetch_free_recommendation() -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(FREE_LLM_RECOMMENDATION_URL)
        resp.raise_for_status()
        return resp.json()


@router.get("/api/models/free-preset")
async def get_free_preset():
    """Ranked free models for the Free council preset (cached, 1h TTL)."""
    now = time.time()
    cached = _free_preset_cache["data"]
    if cached is not None and now - _free_preset_cache["timestamp"] < _FREE_PRESET_CACHE_TTL:
        return cached

    try:
        result = _extract_free_preset(await _fetch_free_recommendation())
        _free_preset_cache["data"] = result
        _free_preset_cache["timestamp"] = now
        return result
    except Exception as e:
        logger.warning("free-llm recommendation feed unavailable: %s", e)
        if cached is not None:
            return cached  # stale beats empty
        return {"models": [], "chairman": None, "updated_at": None,
                "source": "https://shir-man.com/free-llm/"}
