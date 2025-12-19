"""3-stage LLM Council orchestration."""

import re
import json
import logging
import contextvars
from typing import List, Dict, Any, Tuple, Optional

from .toon_encoder import (
    encode_for_llm,
    get_savings_stats,
    aggregate_token_stats,
    is_toon_available
)

logger = logging.getLogger(__name__)

# Request-scoped token stats using contextvars (thread/async safe)
_token_stats_var: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    'token_stats',
    default={"stage1": None, "stage2": None, "stage3": None, "total": None}
)


def reset_token_stats():
    """Reset token stats for a new request. Must be called at start of each request."""
    _token_stats_var.set({
        "stage1": None,
        "stage2": None,
        "stage3": None,
        "total": None
    })


def get_token_stats() -> Dict[str, Any]:
    """Get accumulated token stats for current request."""
    return _token_stats_var.get().copy()


def format_with_toon(data: List[Dict], stage_name: str) -> Tuple[str, Dict]:
    """
    Format data with TOON and track token savings.

    Args:
        data: List of dicts to format
        stage_name: Name of stage for stats tracking (stage1, stage2, stage3)

    Returns:
        Tuple of (formatted_text, stats_dict)
    """
    current_stats = _token_stats_var.get()

    logger.info(f"[TOON] format_with_toon called for {stage_name} with {len(data) if data else 0} items")

    if not data:
        return "", {"json_tokens": 0, "toon_tokens": 0, "saved_percent": 0.0}

    # Encode to TOON
    toon_text = encode_for_llm(data)

    # Calculate stats
    stats = get_savings_stats(data, toon_text)

    # Store stats for this stage (create new dict to avoid mutation issues)
    new_stats = current_stats.copy()
    new_stats[stage_name] = stats

    # Update total
    stages_with_stats = [s for s in ["stage1", "stage2", "stage3"]
                        if new_stats.get(s)]
    if stages_with_stats:
        new_stats["total"] = aggregate_token_stats(
            *[new_stats[s] for s in stages_with_stats]
        )

    # Update the context var
    _token_stats_var.set(new_stats)

    logger.debug(f"[TOON] {stage_name}: JSON={stats['json_tokens']} TOON={stats['toon_tokens']} Saved={stats['saved_percent']}%")

    return toon_text, stats


def safe_serialize(obj: Any) -> str:
    """
    Safely serialize object to string for JSON embedding.
    Avoids invalid escape sequences like \\x that break JSON parsing.
    """
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        # Fallback: convert to string and escape problematic characters
        s = str(obj)
        # Replace invalid escape sequences with their unicode equivalents
        return s.encode('unicode_escape').decode('ascii')
from .config import (
    COUNCIL_MODELS, CHAIRMAN_MODEL, ROUTER_TYPE, TITLE_GENERATION_TIMEOUT,
    ENABLE_MEMORY
)
from .tools import get_available_tools
from .memory import CouncilMemorySystem

# Import router module based on configuration
if ROUTER_TYPE == "ollama":
    from .ollama import query_models_parallel, query_model, query_models_streaming
    # Ollama doesn't have build_message_content, provide a fallback
    def build_message_content(text, images=None):
        if images:
            # Ollama may not support images, return text only with warning
            logger.warning("Ollama router may not support image attachments. Images ignored.")
        return text
elif ROUTER_TYPE == "openrouter":
    from .openrouter import query_models_parallel, query_model, query_models_streaming, build_message_content
else:
    raise ValueError(f"Invalid ROUTER_TYPE: {ROUTER_TYPE}")


def build_context_prompt(conversation_history: List[Dict[str, Any]], user_query: str) -> str:
    """
    Build a prompt with conversation history context.

    Args:
        conversation_history: List of previous messages in the conversation
        user_query: The current user question

    Returns:
        A formatted prompt with context
    """
    if not conversation_history:
        return user_query

    context_parts = []
    for msg in conversation_history:
        if msg.get('role') == 'user':
            context_parts.append(f"User: {msg.get('content', '')}")
        elif msg.get('role') == 'assistant':
            # Include only the final answer from stage3 for context
            if msg.get('stage3') and msg['stage3'].get('response'):
                context_parts.append(f"Council Answer: {msg['stage3']['response']}")

    if not context_parts:
        return user_query

    context = "\n\n".join(context_parts)
    return f"""Previous conversation:
{context}

Current follow-up question: {user_query}

Please answer the follow-up question, taking into account the previous conversation context."""


def build_multimodal_messages(
    user_query: str,
    images: Optional[List[Dict[str, str]]] = None,
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Build messages array for LLM API, supporting both text and images.

    Args:
        user_query: The user's text question
        images: Optional list of image dicts with 'content' (base64 data URI) and 'filename'
        conversation_history: Optional list of previous messages for context

    Returns:
        List of message dicts ready for OpenRouter API
    """
    # Build the text prompt with context
    text_prompt = build_context_prompt(conversation_history or [], user_query)

    # Build message content (text only or multimodal)
    content = build_message_content(text_prompt, images)

    return [{"role": "user", "content": content}]


# Tool detection helpers (Feature 4)
def _has_finance_signal(query: str) -> bool:
    """Check if query has finance-related signals using word boundary matching.

    Uses regex word boundaries to avoid false positives like:
    - "сценария" matching "цена" (price)
    """
    q = query.lower()
    finance_signals = [
        # English
        "price", "stock", "stocks", "shares", "ticker", "market cap", "quote",
        # Russian - use word boundaries to avoid matching substrings
        "цена", "цены", "акция", "акции", "акций", "котировка", "котировки", "биржа", "курс"
    ]
    # Build regex pattern with word boundaries for each signal
    for sig in finance_signals:
        # Use \b for English, but for Russian we need custom boundary
        # matching (start/end of string, space, or punctuation)
        if sig.isascii():
            pattern = rf'\b{re.escape(sig)}\b'
        else:
            # For Cyrillic, match at word boundaries (non-letter chars)
            pattern = rf'(?<![а-яё]){re.escape(sig)}(?![а-яё])'
        if re.search(pattern, q, re.IGNORECASE):
            return True
    return False


def _has_calc_signal(query: str) -> bool:
    q = query.lower()
    calc_signals = {
        # English
        "calculate", "compute", "math", "sum", "multiply", "divide", "add", "subtract",
        # Russian
        "посчитай", "вычисли", "калькулятор", "сумма", "умножь", "раздели", "сложи", "вычти",
        "процент", "процентов", "%", "сколько будет"
    }
    # Check for math expressions like "100 * 25" or "100 + 200"
    has_math_expr = bool(re.search(r'\d+\s*[*\/+\-^x×÷]\s*\d+', q, re.IGNORECASE))
    return any(sig in q for sig in calc_signals) or has_math_expr


def _has_search_signal(query: str) -> bool:
    q = query.lower()
    search_signals = {
        # English
        "search", "latest", "news", "current", "recent", "today", "update",
        # Russian
        "поиск", "найди", "новости", "новость", "последние", "последняя",
        "свежие", "свежая", "текущие", "сегодня", "актуальн"
    }
    return any(sig in q for sig in search_signals)


def _has_research_signal(query: str) -> bool:
    q = query.lower()
    research_signals = {
        # English
        "wikipedia", "wiki", "research", "paper", "arxiv", "definition", "history",
        # Russian
        "википедия", "вики", "исследование", "статья", "определение", "история", "что такое", "кто такой"
    }
    return any(sig in q for sig in research_signals)


def requires_tools(query: str) -> bool:
    """Heuristic: only run tools when signals are clear."""
    return (
        _has_finance_signal(query)
        or _has_calc_signal(query)
        or _has_search_signal(query)
        or _has_research_signal(query)
    )


async def optimize_search_query(user_query: str, chairman: str = None) -> str:
    """
    Use Chairman model to generate an optimized web search query.
    The Chairman is prompted as an expert in composing search queries
    to find the latest and most relevant information.

    Args:
        user_query: The original user question
        chairman: Optional chairman model override (defaults to CHAIRMAN_MODEL)

    Returns:
        Optimized search query string
    """
    chairman_model = chairman if chairman else CHAIRMAN_MODEL

    prompt = f"""You are an expert at composing web search queries to find the latest and most relevant information.

Given the user's question, generate the BEST possible web search query that will:
1. Find the most recent and up-to-date information
2. Be specific enough to get relevant results
3. Use effective search operators if helpful

User's question: {user_query}

Respond with ONLY the search query, nothing else. No explanations, no quotes, just the search query itself."""

    messages = [{"role": "user", "content": prompt}]

    try:
        logger.info("[WEB_SEARCH] Optimizing search query with Chairman: %s", chairman_model)
        response = await query_model(chairman_model, messages, stage="SEARCH_OPTIMIZE")

        if response and response.get('content'):
            optimized_query = response['content'].strip()
            # Remove any quotes if the model wrapped the query
            optimized_query = optimized_query.strip('"\'')
            logger.info("[WEB_SEARCH] Optimized query: %s", optimized_query[:100])
            return optimized_query
        else:
            logger.warning("[WEB_SEARCH] Chairman returned empty response, using original query")
            return user_query
    except Exception as e:
        logger.error("[WEB_SEARCH] Failed to optimize query: %s", e)
        return user_query


def run_tavily_direct(query: str) -> List[Dict[str, str]]:
    """
    Run web search (Tavily or Exa) directly with the given query.

    Args:
        query: The search query to execute

    Returns:
        List of tool output dicts with 'tool' and 'result' keys
    """
    tools = get_available_tools()

    # Try Tavily first, then Exa
    tavily_tool = next((t for t in tools if t.name == "tavily_search"), None)
    exa_tool = next((t for t in tools if t.name == "exa_search"), None)

    search_tool = tavily_tool or exa_tool

    if not search_tool:
        logger.warning("[WEB_SEARCH] No search tool available (Tavily or Exa)")
        return []

    tool_name = search_tool.name
    try:
        logger.info("[WEB_SEARCH] Executing %s search: %s", tool_name, query[:100])
        output = search_tool.invoke(query)
        if output:
            try:
                output_str = json.dumps(output, ensure_ascii=False)
            except (TypeError, ValueError):
                output_str = str(output)

            if len(output_str) > 24000:
                output_str = output_str[:24000] + "..."

            logger.info("[WEB_SEARCH] %s returned %d chars", tool_name, len(output_str))
            return [{"tool": tool_name, "result": output_str}]
    except Exception as e:
        logger.error("[WEB_SEARCH] %s search failed: %s", tool_name, e)

    return []


def extract_ticker_candidates(text: str) -> List[str]:
    """Extract probable stock tickers from text."""
    if not text:
        return []

    stop_words = {
        "THE", "AND", "FOR", "WITH", "TODAY", "PRICE", "STOCK", "STOCKS", "SHARES", "HOW",
        "WHAT", "IS", "ARE", "OF", "IN", "ON", "TO", "BY", "VS", "VERSUS", "GOOD",
        "BETTER", "BAD", "SHARE", "MARKET", "QUESTION", "ABOUT"
    }

    name_map = {
        # English names
        "APPLE": "AAPL", "TESLA": "TSLA", "GOOGLE": "GOOGL", "ALPHABET": "GOOGL",
        "MICROSOFT": "MSFT", "AMAZON": "AMZN", "META": "META", "FACEBOOK": "META",
        "NVIDIA": "NVDA", "NETFLIX": "NFLX", "AMD": "AMD", "IBM": "IBM",
        "SHOPIFY": "SHOP", "SNOW": "SNOW",
        # Russian names (uppercase for matching)
        "ЭППЛ": "AAPL", "ТЕСЛА": "TSLA", "ГУГЛ": "GOOGL", "МАЙКРОСОФТ": "MSFT",
        "АМАЗОН": "AMZN", "МЕТА": "META", "ФЕЙСБУК": "META", "НВИДИА": "NVDA",
        "НЕТФЛИКС": "NFLX",
    }

    # Match both Latin and Cyrillic words
    tokens = re.findall(r"\b[A-ZА-ЯЁ]{1,15}\b", text.upper())
    seen = set()
    candidates: List[str] = []

    for tok in tokens:
        mapped = name_map.get(tok)
        if mapped:
            if mapped not in seen:
                seen.add(mapped)
                candidates.append(mapped)
            continue
        if tok in stop_words:
            continue
        # Only add Latin tickers (1-5 chars)
        if 1 <= len(tok) <= 5 and tok.isascii():
            if tok not in seen:
                seen.add(tok)
                candidates.append(tok)

    return candidates


def run_stock_for_tickers(stock_tool, tickers: List[str], limit: int) -> List[Dict[str, str]]:
    """Run stock tool for a list of tickers and return valid price outputs."""
    results: List[Dict[str, str]] = []
    seen = set()

    for ticker in tickers:
        if len(results) >= limit:
            break
        if ticker in seen:
            continue
        seen.add(ticker)
        try:
            output = stock_tool.run(ticker)
            if not output:
                continue
            output_str = safe_serialize(output)
            if "$" in output_str or "price=" in output_str.lower():
                results.append({"tool": stock_tool.name, "result": output_str})
        except Exception as e:
            logger.debug("Stock tool failed for ticker %s: %s", ticker, e)
            continue

    return results


def run_tools_for_query(query: str, limit: int = 3) -> List[Dict[str, str]]:
    """Run available tools against the query to enrich context."""
    results: List[Dict[str, str]] = []
    tools = get_available_tools()
    stock_tool = next((t for t in tools if t.name == "stock_data"), None)
    web_tool = next((t for t in tools if t.name == "web_search"), None)
    tavily_tool = next((t for t in tools if t.name == "tavily_search"), None)
    exa_tool = next((t for t in tools if t.name == "exa_search"), None)
    finance_intent = _has_finance_signal(query)
    search_intent = _has_search_signal(query)

    # If user asks for news/search AND finance, prioritize search (Tavily) first
    # This handles cases like "AI healthcare news" where stock tickers like "AI"
    # shouldn't override the search intent
    if search_intent and finance_intent:
        logger.debug("[TOOLS] Both search and finance intent detected, prioritizing search")
        finance_intent = False  # Let Tavily handle it

    # If ticker-like symbols are present, try them first
    if finance_intent:
        tickers = extract_ticker_candidates(query)
        if tickers and stock_tool:
            results.extend(run_stock_for_tickers(stock_tool, tickers, limit))
            if results:
                return results

        # Fallback: try to infer tickers from web search output
        if not results and stock_tool and web_tool:
            try:
                web_output = web_tool.run(query)
                inferred_tickers = extract_ticker_candidates(str(web_output))
                if inferred_tickers:
                    results.extend(run_stock_for_tickers(stock_tool, inferred_tickers, limit))
                    if results:
                        return results
            except Exception as e:
                logger.debug("Web search fallback failed: %s", e)

    # Search tools: only run when there's explicit search intent (avoid paid calls on non-search prompts).
    logger.debug(
        "[TOOLS] Query: %s... | has_search=%s | tavily=%s | exa=%s | web=%s",
        query[:50],
        search_intent,
        tavily_tool is not None,
        exa_tool is not None,
        web_tool is not None,
    )
    if search_intent and (tavily_tool or exa_tool or web_tool):
        search_tool = tavily_tool or exa_tool or web_tool
        try:
            logger.debug("[TOOLS] Calling %s...", search_tool.name)
            output = search_tool.invoke(query)
            if output:
                output_str = safe_serialize(output)
                logger.debug("[TOOLS] %s returned %d chars", search_tool.name, len(output_str))
                if len(output_str) > 24000:
                    output_str = output_str[:24000] + "..."
                results.append({"tool": search_tool.name, "result": output_str})
                return results  # Search output is comprehensive, no need for other search tools
        except Exception as e:
            logger.warning("[TOOLS] %s error: %s", search_tool.name, e)

    for tool in tools:
        if tool.name == "stock_data":
            continue
        if tool.name in ("web_search", "tavily_search", "exa_search"):
            continue  # Handled above (and gated by search intent)
        if len(results) >= limit:
            break
        # Skip tools that don't match intent
        if tool.name == "calculator" and not _has_calc_signal(query):
            continue
        if tool.name in ("wikipedia", "arxiv") and not _has_research_signal(query):
            continue
        try:
            output = tool.run(query)
            if output:
                output_str = safe_serialize(output)
                if len(output_str) > 500:
                    output_str = output_str[:500] + "..."
                results.append({"tool": tool.name, "result": output_str})
        except Exception as e:
            logger.debug("Tool %s failed: %s", tool.name, e)
            continue

    return results


async def stage1_collect_responses(
    user_query: str,
    conversation_history: List[Dict[str, Any]] = None,
    models: List[str] = None,
    images: Optional[List[Dict[str, str]]] = None,
    conversation_id: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """
    Stage 1: Collect individual responses from all council models.

    Args:
        user_query: The user's question
        conversation_history: Optional list of previous messages for context
        models: Optional list of model IDs to use (defaults to COUNCIL_MODELS)
        images: Optional list of image attachments for multimodal queries
        conversation_id: Optional conversation ID for memory system

    Returns:
        Tuple of (stage1_results, tool_outputs)
    """
    # Build messages with optional image support
    messages = build_multimodal_messages(user_query, images, conversation_history)

    # Add tool context if the query suggests tool usage (Feature 4)
    tool_outputs: List[Dict[str, str]] = []
    logger.debug("[STAGE1] requires_tools(%s...): %s", user_query[:30], requires_tools(user_query))
    if requires_tools(user_query):
        tool_outputs = run_tools_for_query(user_query)
        logger.debug("[STAGE1] tool_outputs: %d results", len(tool_outputs))
        if tool_outputs:
            tool_text = """IMPORTANT: Use the following real-time search results to answer the user's question.
This data is current and should be used as the primary source for your response.

Search Results:
""" + "\n".join(
                f"- {item['tool']}: {item['result']}" for item in tool_outputs
            )
            messages.insert(0, {"role": "system", "content": tool_text})

    # Add memory context if enabled (Feature 4)
    if ENABLE_MEMORY and conversation_id:
        try:
            memory = CouncilMemorySystem(conversation_id)
            memory_ctx = memory.get_context(user_query)
            if memory_ctx:
                messages.insert(0, {"role": "system", "content": f"Relevant past exchanges:\n{memory_ctx}"})
        except Exception as e:
            logger.warning("Memory context retrieval failed: %s", e)

    # Use provided models or fall back to default
    council_models = models if models else COUNCIL_MODELS

    logger.debug("[STAGE1] ========== STAGE 1: COLLECT RESPONSES ==========")
    logger.debug("[STAGE1] Query: %s...", user_query[:80])
    logger.debug("[STAGE1] Models: %s", council_models)
    logger.debug("[STAGE1] Messages: %d (system=%d)", len(messages), sum(1 for m in messages if m.get('role')=='system'))

    # Query all models in parallel
    responses = await query_models_parallel(council_models, messages, stage="STAGE1")

    # Format results - include both successes and errors
    stage1_results = []
    for model, response in responses.items():
        if response is None:
            # Shouldn't happen with new error handling, but safety fallback
            stage1_results.append({
                "model": model,
                "error": True,
                "error_type": "unknown",
                "error_message": "No response received"
            })
        elif response.get('error'):
            # Include error information
            stage1_results.append({
                "model": model,
                "error": True,
                "error_type": response.get('error_type', 'unknown'),
                "error_message": response.get('error_message', 'Unknown error')
            })
        else:
            # Successful response
            stage1_results.append({
                "model": model,
                "response": response.get('content', '')
            })

    return stage1_results, tool_outputs


async def stage1_collect_responses_streaming(
    user_query: str,
    conversation_history: List[Dict[str, Any]] = None,
    models: List[str] = None,
    images: Optional[List[Dict[str, str]]] = None,
    conversation_id: Optional[str] = None,
    force_web_search: bool = False,
    chairman: str = None
):
    """
    Stage 1: Collect individual responses from all council models with streaming.
    Yields each model's response as soon as it's ready.

    Args:
        user_query: The user's question
        conversation_history: Optional list of previous messages for context
        models: Optional list of model IDs to use (defaults to COUNCIL_MODELS)
        images: Optional list of image attachments for multimodal queries
        conversation_id: Optional conversation ID for memory system
        force_web_search: If True, Chairman optimizes query and runs Tavily search
        chairman: Optional chairman model for search query optimization

    Yields:
        Dict with 'model', 'response', and optionally 'tool_outputs' keys
    """
    # Build messages with optional image support
    messages = build_multimodal_messages(user_query, images, conversation_history)

    # Add tool context
    tool_outputs: List[Dict[str, str]] = []

    # Force web search: Chairman optimizes query, then Tavily searches
    if force_web_search:
        logger.info("[STAGE1-STREAM] Force web search enabled, optimizing query with Chairman")
        optimized_query = await optimize_search_query(user_query, chairman)
        tool_outputs = run_tavily_direct(optimized_query)
        logger.info("[STAGE1-STREAM] Web search returned %d results", len(tool_outputs))
    # Regular tool detection (Feature 4)
    elif requires_tools(user_query):
        logger.debug("[STAGE1-STREAM] requires_tools(%s...): %s", user_query[:30], requires_tools(user_query))
        tool_outputs = run_tools_for_query(user_query)
        logger.debug("[STAGE1-STREAM] tool_outputs: %d results", len(tool_outputs))

    if tool_outputs:
        tool_text = """IMPORTANT: Use the following real-time search results to answer the user's question.
This data is current and should be used as the primary source for your response.

Search Results:
""" + "\n".join(
            f"- {item['tool']}: {item['result']}" for item in tool_outputs
        )
        messages.insert(0, {"role": "system", "content": tool_text})
        logger.debug("[STAGE1-STREAM] Injected system message with %d chars", len(tool_text))

    # Add memory context if enabled (Feature 4)
    if ENABLE_MEMORY and conversation_id:
        try:
            memory = CouncilMemorySystem(conversation_id)
            memory_ctx = memory.get_context(user_query)
            if memory_ctx:
                messages.insert(0, {"role": "system", "content": f"Relevant past exchanges:\n{memory_ctx}"})
        except Exception as e:
            logger.warning("Memory context retrieval failed (streaming): %s", e)

    # Use provided models or fall back to default
    council_models = models if models else COUNCIL_MODELS

    logger.debug("[STAGE1-STREAM] Messages count: %d (system=%d)", len(messages), sum(1 for m in messages if m.get('role')=='system'))

    # First yield: tool outputs (so frontend knows about them)
    if tool_outputs:
        yield {"type": "tool_outputs", "tool_outputs": tool_outputs}

    # Query all models in parallel and yield results as they complete
    async for model, response in query_models_streaming(council_models, messages):
        if response is None:
            # Shouldn't happen with new error handling, but safety fallback
            yield {
                "model": model,
                "error": True,
                "error_type": "unknown",
                "error_message": "No response received"
            }
        elif response.get('error'):
            # Include error information
            yield {
                "model": model,
                "error": True,
                "error_type": response.get('error_type', 'unknown'),
                "error_message": response.get('error_message', 'Unknown error')
            }
        else:
            # Successful response
            yield {
                "model": model,
                "response": response.get('content', '')
            }


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    models: List[str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2: Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1
        models: Optional list of model IDs to use (defaults to COUNCIL_MODELS)

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # VALIDATION: Skip Stage 2 if no Stage 1 results
    if not stage1_results:
        logger.warning("[STAGE2] No Stage 1 results to rank, skipping Stage 2")
        return [], {}

    # Filter out empty responses from Stage 1
    valid_stage1 = [r for r in stage1_results if r.get('response') and r['response'].strip()]
    if not valid_stage1:
        logger.warning("[STAGE2] All Stage 1 responses are empty, skipping Stage 2")
        return [], {}

    if len(valid_stage1) < len(stage1_results):
        logger.info("[STAGE2] Filtered %d empty responses, using %d valid responses",
                   len(stage1_results) - len(valid_stage1), len(valid_stage1))

    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [chr(65 + i) for i in range(len(valid_stage1))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, valid_stage1)
    }

    # Build the ranking prompt - use TOON for token efficiency
    # Prepare data for TOON encoding
    responses_data = [
        {"label": f"Response {label}", "content": result['response']}
        for label, result in zip(labels, valid_stage1)
    ]

    # Format with TOON and track stats
    responses_toon, _ = format_with_toon(responses_data, "stage2")

    # For the prompt, use a readable format that includes TOON
    responses_text = f"""The responses are provided in TOON (Token-Oriented Object Notation) format for efficiency:

{responses_toon}"""

    ranking_prompt = f"""You are evaluating different responses to the following question:

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

    messages = [{"role": "user", "content": ranking_prompt}]

    # OPTIMIZATION: Use only models that succeeded in Stage 1
    # This avoids rate limits - models that just responded are less likely to be rate-limited
    # than making fresh requests to models that may have failed
    stage1_successful_models = [r['model'] for r in valid_stage1]

    # If custom models provided, use intersection with successful models
    # Otherwise use all Stage 1 successful models
    if models:
        # Use custom models that are also in successful list
        council_models = [m for m in models if m in stage1_successful_models]
        if not council_models:
            # Fallback: if no intersection, use Stage 1 successful models
            council_models = stage1_successful_models
            logger.info("[STAGE2] Custom models not in Stage 1 success list, using Stage 1 models")
    else:
        council_models = stage1_successful_models

    logger.debug("[STAGE2] ========== STAGE 2: COLLECT RANKINGS ==========")
    logger.debug("[STAGE2] Evaluating %d valid responses", len(valid_stage1))
    logger.debug("[STAGE2] Using %d models from Stage 1 successes: %s", len(council_models), council_models)

    # Get rankings from models in parallel
    responses = await query_models_parallel(council_models, messages, stage="STAGE2")

    # Format results - include both successes and errors
    stage2_results = []
    failed_count = 0
    for model, response in responses.items():
        if response is None:
            # Shouldn't happen with new error handling
            failed_count += 1
            stage2_results.append({
                "model": model,
                "error": True,
                "error_type": "unknown",
                "error_message": "No response received"
            })
            logger.warning("[STAGE2] Model %s returned None", model)
        elif response.get('error'):
            # Include error information
            failed_count += 1
            stage2_results.append({
                "model": model,
                "error": True,
                "error_type": response.get('error_type', 'unknown'),
                "error_message": response.get('error_message', 'Unknown error')
            })
            logger.warning("[STAGE2] Model %s failed: %s", model, response.get('error_message'))
        else:
            full_text = response.get('content', '')
            if full_text and full_text.strip():  # Additional validation
                parsed = parse_ranking_from_text(full_text)
                stage2_results.append({
                    "model": model,
                    "ranking": full_text,
                    "parsed_ranking": parsed
                })
            else:
                failed_count += 1
                stage2_results.append({
                    "model": model,
                    "error": True,
                    "error_type": "empty",
                    "error_message": "Model returned empty response"
                })
                logger.warning("[STAGE2] Model %s returned empty content", model)

    # Log summary
    if failed_count > 0:
        logger.warning("[STAGE2] %d/%d models failed, %d successful rankings",
                      failed_count, len(council_models), len(stage2_results))

    return stage2_results, label_to_model


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    chairman: str = None,
    tool_outputs: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Rankings from Stage 2
        chairman: Optional chairman model ID (defaults to CHAIRMAN_MODEL)
        tool_outputs: Optional tool outputs from Stage 1

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Use provided chairman or fall back to default
    chairman_model = chairman if chairman else CHAIRMAN_MODEL

    # VALIDATION: Handle empty Stage 1 results
    if not stage1_results:
        logger.error("[STAGE3] No Stage 1 results to synthesize")
        return {
            "model": chairman_model,
            "response": "Error: No model responses were collected. All models may have failed or been rate-limited. Please try again.",
            "error": True
        }

    # Build comprehensive context for chairman using TOON for efficiency
    # Prepare stage1 data for TOON (use encode_for_llm directly since we already
    # counted these tokens in stage2_collect_rankings - avoid double-counting)
    stage1_data = [
        {"model": result['model'], "response": result['response']}
        for result in stage1_results
        if result.get('response')
    ]
    stage1_toon = encode_for_llm(stage1_data)
    stage1_text = f"Data in TOON format:\n{stage1_toon}"

    # Handle empty Stage 2 results gracefully
    has_rankings = stage2_results and len(stage2_results) > 0
    if has_rankings:
        # Prepare stage2 rankings for TOON (track as "stage3" - rankings data sent to chairman)
        stage2_data = [
            {"model": result['model'], "ranking": result['ranking']}
            for result in stage2_results
            if result.get('ranking')
        ]
        stage2_toon, _ = format_with_toon(stage2_data, "stage3")
        stage2_text = f"Data in TOON format:\n{stage2_toon}"
    else:
        stage2_text = ""
        logger.warning("[STAGE3] No peer rankings available - Stage 2 may have failed")

    # Add tool outputs if available
    tools_text = ""
    if tool_outputs:
        tools_text = "\n\nTOOL OUTPUTS:\n" + "\n".join(
            f"- {t.get('tool')}: {t.get('result')}" for t in tool_outputs
        )

    # Build prompt based on whether rankings are available
    if has_rankings:
        chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}{tools_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""
    else:
        # Fallback prompt when no rankings available
        chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question.

Note: Peer rankings were not available due to rate limiting or other issues.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}{tools_text}

Your task as Chairman is to synthesize all of these responses into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- Any patterns of agreement or disagreement between models
- The completeness and accuracy of each response

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    logger.debug("[STAGE3] ========== STAGE 3: CHAIRMAN SYNTHESIS ==========")
    logger.debug("[STAGE3] Chairman: %s", chairman_model)
    logger.debug("[STAGE3] Input: %d responses, %d rankings", len(stage1_results), len(stage2_results))
    if tool_outputs:
        logger.debug("[STAGE3] Tool outputs: %d", len(tool_outputs))

    # Query the chairman model
    response = await query_model(chairman_model, messages, stage="STAGE3")

    if response is None:
        # Try fallback: use models from Stage 1 as chairman (try each until one works)
        logger.warning("Chairman model %s failed. Attempting fallback with preset models...", chairman_model)

        # Collect all Stage 1 models (excluding chairman if it was in the list)
        fallback_models = [
            r['model'] for r in stage1_results
            if r.get('response') and r['model'] != chairman_model
        ]

        for fallback_model in fallback_models:
            logger.info("Attempting to use %s as fallback chairman (%d models remaining)...",
                       fallback_model, len(fallback_models) - fallback_models.index(fallback_model) - 1)
            fallback_response = await query_model(fallback_model, messages, stage="STAGE3_FALLBACK")

            if fallback_response is not None and fallback_response.get('content'):
                logger.info("Fallback successful with model %s", fallback_model)
                return {
                    "model": fallback_model,
                    "response": fallback_response.get('content', ''),
                    "fallback_used": True,
                    "original_chairman": chairman_model
                }
            else:
                logger.warning("Fallback model %s also failed, trying next...", fallback_model)

        # All fallbacks failed, return error with context
        error_msg = (
            f"Error: Unable to generate final synthesis. "
            f"Chairman model '{chairman_model}' and all {len(fallback_models)} fallback models failed to respond. "
            f"All models may be rate-limited. Please try again in a few minutes."
        )
        logger.error(error_msg)
        return {
            "model": chairman_model,
            "response": error_msg,
            "error": True,
            "tried_fallbacks": fallback_models
        }

    return {
        "model": chairman_model,
        "response": response.get('content', '')
    }


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [re.search(r'Response [A-Z]', m).group() for m in numbered_matches]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in stage2_results:
        ranking_text = ranking['ranking']

        # Parse the ranking from the structured format
        parsed_ranking = parse_ranking_from_text(ranking_text)

        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    # Calculate average position for each model
    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x['average_rank'])

    return aggregate


async def generate_conversation_title(user_query: str) -> str:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    messages = [{"role": "user", "content": title_prompt}]

    # Use the chairman model for title generation
    # Increased timeout for Ollama models which may need time to load
    response = await query_model(CHAIRMAN_MODEL, messages, timeout=TITLE_GENERATION_TIMEOUT)

    if response is None:
        # Fallback to a generic title
        return "New Conversation"

    title = response.get('content', 'New Conversation').strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip('"\'')

    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."

    return title


async def run_full_council(
    user_query: str,
    conversation_history: List[Dict[str, Any]] = None,
    images: Optional[List[Dict[str, str]]] = None,
    conversation_id: Optional[str] = None
) -> Tuple[List, List, Dict, Dict]:
    """
    Run the complete 3-stage council process.

    Args:
        user_query: The user's question
        conversation_history: Optional list of previous messages for context
        images: Optional list of image attachments for multimodal queries
        conversation_id: Optional conversation ID for memory system

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    # Reset token stats for this request (request-scoped via contextvars)
    reset_token_stats()

    # Stage 1: Collect individual responses (now returns tool_outputs)
    stage1_results, tool_outputs = await stage1_collect_responses(
        user_query,
        conversation_history,
        images=images,
        conversation_id=conversation_id
    )

    # If no models responded successfully, return error
    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {}

    # Stage 2: Collect rankings
    stage2_results, label_to_model = await stage2_collect_rankings(user_query, stage1_results)

    # Calculate aggregate rankings
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Stage 3: Synthesize final answer (now includes tool_outputs)
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results,
        tool_outputs=tool_outputs
    )

    # Save exchange to memory if enabled (Feature 4)
    if ENABLE_MEMORY and conversation_id:
        try:
            memory = CouncilMemorySystem(conversation_id)
            memory.save_exchange(user_query, stage3_result.get("response", ""))
        except Exception as e:
            logger.warning("Memory save failed: %s", e)

    # Prepare metadata (include token_stats from TOON encoding)
    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
        "tool_outputs": tool_outputs,
        "token_stats": get_token_stats()
    }

    return stage1_results, stage2_results, stage3_result, metadata
