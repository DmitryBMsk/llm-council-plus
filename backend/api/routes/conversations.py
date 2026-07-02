"""Conversation endpoints — /api/conversations/*, /api/upload."""

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Optional, Tuple
import uuid
import json
import asyncio
import time
import logging

from ... import storage
from ... import config
from ...council import (
    run_full_council, generate_conversation_title,
    stage1_collect_responses_streaming,
    stage2_collect_rankings, stage3_synthesize_final,
    calculate_aggregate_rankings, reset_token_stats, get_token_stats
)
from ...file_parser import parse_file, get_supported_extensions, is_image_file
from ..deps import get_current_user, _ownership_username
from .models import _get_models_cache_lock, _models_cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["conversations"])
STAGE1_HEARTBEAT_INTERVAL = 15


async def _next_stage1_item(stage1_stream):
    return await stage1_stream.__anext__()


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    models: Optional[List[str]] = Field(default=None, max_length=20)  # Council models (max 20)
    chairman: Optional[str] = Field(default=None, max_length=100)  # Chairman/judge model
    username: Optional[str] = Field(default=None, max_length=50)  # User who created the conversation
    execution_mode: Optional[str] = Field(default=None, pattern="^(chat_only|chat_ranking|full)$")
    router_type: Optional[str] = Field(default=None, pattern="^(openrouter|ollama)$")


class FileAttachment(BaseModel):
    """File attachment with parsed content."""
    filename: str = Field(max_length=255, pattern=r'^[^/\\<>:"|?*\x00-\x1f]+$')  # Safe filename
    file_type: str = Field(max_length=20)  # 'pdf', 'txt', 'md', or 'image'
    content: str = Field(max_length=5_000_000)  # 5MB limit per file (base64)
    mime_type: Optional[str] = Field(default=None, max_length=100)


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str = Field(min_length=1, max_length=100_000)  # 100KB text limit
    attachments: Optional[List[FileAttachment]] = Field(default=None, max_length=5)  # Max 5 attachments
    temporary: Optional[bool] = False  # If True, don't save to storage (Feature 5)
    web_search: Optional[bool] = False  # DEPRECATED: use web_search_provider
    web_search_provider: Optional[str] = Field(default=None, pattern="^(duckduckgo|tavily|exa|brave)$")

    @field_validator('attachments')
    @classmethod
    def validate_total_attachment_size(cls, v):
        """Validate total size of all attachments (max 20MB total)."""
        if v is None:
            return v
        total_size = sum(len(att.content) for att in v)
        max_total_size = 20_000_000  # 20MB total
        if total_size > max_total_size:
            raise ValueError(f"Total attachment size ({total_size / 1_000_000:.1f}MB) exceeds limit (20MB)")
        return v


class UpdateTitleRequest(BaseModel):
    """Request to update conversation title (Feature 5)."""
    title: str = Field(min_length=1, max_length=200)  # Reasonable title length


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int
    username: Optional[str] = None


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]
    models: Optional[List[str]] = None
    chairman: Optional[str] = None
    username: Optional[str] = None
    execution_mode: Optional[str] = None


def separate_attachments(attachments: Optional[List[FileAttachment]]) -> Tuple[List[FileAttachment], List[Dict[str, str]]]:
    """
    Separate text attachments from image attachments.

    Args:
        attachments: List of file attachments

    Returns:
        Tuple of (text_attachments, image_attachments)
        image_attachments are formatted for multimodal API
    """
    if not attachments:
        return [], []

    text_attachments = []
    image_attachments = []

    for att in attachments:
        if att.file_type == 'image':
            # Format for multimodal API
            image_attachments.append({
                "content": att.content,  # base64 data URI
                "filename": att.filename
            })
        else:
            text_attachments.append(att)

    return text_attachments, image_attachments


def build_query_with_attachments(content: str, attachments: Optional[List[FileAttachment]]) -> str:
    """Build full query including text file attachments (not images)."""
    if not attachments:
        return content

    # Filter out image attachments - they're handled separately
    text_attachments = [att for att in attachments if att.file_type != 'image']

    if not text_attachments:
        return content

    attachment_texts = []
    for att in text_attachments:
        attachment_texts.append(f"--- File: {att.filename} ({att.file_type}) ---\n{att.content}\n--- End of {att.filename} ---")

    attachments_section = "\n\n".join(attachment_texts)

    return f"""{content}

The user has attached the following file(s) for analysis:

{attachments_section}

Please analyze the attached content in the context of the user's question."""


@router.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations(current_user: str = Depends(get_current_user)):
    """List all conversations (metadata only). Requires authentication."""
    return storage.list_conversations(username=_ownership_username(current_user))


@router.post("/api/conversations", response_model=Conversation)
async def create_conversation(
    request: CreateConversationRequest,
    current_user: str = Depends(get_current_user)
):
    """Create a new conversation. Requires authentication."""
    # Validate chairman model context length if specified
    router_type = (getattr(request, "router_type", None) or config.ROUTER_TYPE or "openrouter").strip().lower()
    async with _get_models_cache_lock():
        cache_entry = _models_cache.get(router_type)
    if request.chairman and cache_entry and cache_entry.get("data"):
        models = cache_entry["data"].get("models", [])
        chairman_model = next((m for m in models if m["id"] == request.chairman), None)
        if chairman_model:
            context_length = chairman_model.get("contextLength", 0)
            if context_length < config.MIN_CHAIRMAN_CONTEXT:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Chairman model {request.chairman} has insufficient context length "
                        f"({context_length}). Minimum required: {config.MIN_CHAIRMAN_CONTEXT}"
                    ),
                )

    conversation_id = str(uuid.uuid4())
    # Always use the authenticated identity — never trust client-supplied username
    conversation = storage.create_conversation(
        conversation_id,
        models=request.models,
        chairman=request.chairman,
        username=current_user,
        execution_mode=request.execution_mode or "full",
        router_type=router_type,
    )
    return conversation


@router.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: str,
    current_user: str = Depends(get_current_user)
):
    """Get a specific conversation with all its messages. Requires authentication."""
    conversation = storage.get_conversation(conversation_id, username=_ownership_username(current_user))
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.delete("/api/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: str = Depends(get_current_user)
):
    """Delete a specific conversation. Requires authentication."""
    if not storage.delete_conversation(conversation_id, username=_ownership_username(current_user)):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted", "id": conversation_id}


@router.patch("/api/conversations/{conversation_id}/title")
async def update_title(
    conversation_id: str,
    request: UpdateTitleRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Update the title of a conversation (Feature 5). Requires authentication.
    Works with all storage backends: JSON, PostgreSQL, MySQL.
    """
    try:
        storage.update_conversation_title(conversation_id, request.title, username=_ownership_username(current_user))
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {
        "success": True,
        "message": "Title updated",
        "title": request.title
    }


@router.delete("/api/conversations")
async def delete_all_conversations(current_user: str = Depends(get_current_user)):
    """Delete all conversations for the current user. Requires authentication."""
    storage.delete_all_conversations(username=_ownership_username(current_user))
    return {"status": "deleted", "count": "all"}


@router.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user)
):
    """
    Upload and parse a file (PDF, TXT, MD, or images). Requires authentication.
    Returns the parsed content that can be attached to a message.
    For images, returns base64 data URI.
    """
    # Check file extension
    supported = get_supported_extensions()
    filename = file.filename or "unknown"
    ext = '.' + filename.lower().split('.')[-1] if '.' in filename else ''

    if ext not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Supported: {', '.join(supported)}"
        )

    try:
        # Read file content
        file_content = await file.read()

        # Enforce size limits BEFORE parsing. PDFs especially can be small on
        # disk yet expand to gigabytes of memory while rendering (a "PDF bomb"),
        # so the cap must run before parse_file(), not after.
        max_image_size = 20 * 1024 * 1024  # 20MB
        max_file_size = 20 * 1024 * 1024   # 20MB for PDF / text / markdown
        if is_image_file(filename):
            if len(file_content) > max_image_size:
                raise HTTPException(
                    status_code=400,
                    detail="Image file too large. Maximum size is 20MB."
                )
        elif len(file_content) > max_file_size:
            raise HTTPException(
                status_code=400,
                detail="File too large. Maximum size is 20MB."
            )

        # Parse off the event loop: PDF parsing (pymupdf4llm) is CPU-bound and
        # would otherwise stall every concurrent SSE stream.
        parsed_content, file_type = await asyncio.to_thread(parse_file, filename, file_content)

        # Build response
        response = {
            "filename": filename,
            "file_type": file_type,
            "content": parsed_content,
        }

        # For images, add mime_type and byte size instead of char_count
        if file_type == 'image':
            from ...file_parser import get_image_mime_type
            response["mime_type"] = get_image_mime_type(filename)
            response["byte_size"] = len(file_content)
            response["char_count"] = 0  # For compatibility with existing frontend
        else:
            # Truncate text content if too long (to avoid token limits)
            max_chars = 50000  # ~12.5k tokens approximately
            if len(parsed_content) > max_chars:
                parsed_content = parsed_content[:max_chars] + "\n\n... [Content truncated due to length]"
                response["content"] = parsed_content
            response["char_count"] = len(parsed_content)

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error parsing file: {str(e)}"
        )


@router.post("/api/conversations/{conversation_id}/message")
async def send_message(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Send a message and run the 3-stage council process. Requires authentication.
    Returns the complete response with all stages.

    Supports temporary mode (Feature 5): if request.temporary=True,
    conversation is not saved to storage.
    """
    # Separate image attachments from text attachments
    _, image_attachments = separate_attachments(request.attachments)

    # Build full query with text attachments only (images handled separately)
    full_query = build_query_with_attachments(request.content, request.attachments)

    # For temporary mode, skip conversation existence check and storage operations
    if request.temporary:
        # Run the 3-stage council process without saving
        try:
            stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
                full_query,
                conversation_history=None,
                images=image_attachments if image_attachments else None,
                conversation_id=None  # No conversation_id for temporary chat
            )
        except ValueError as e:
            # Translate configuration errors (e.g., no council models) to 400
            raise HTTPException(status_code=400, detail=str(e))

        return {
            "stage1": stage1_results,
            "stage2": stage2_results,
            "stage3": stage3_result,
            "metadata": metadata,
            "temporary": True
        }

    # Normal mode: save to storage
    # Check if conversation exists and is owned by current user
    ownership = _ownership_username(current_user)
    conversation = storage.get_conversation(conversation_id, username=ownership)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message (store original content, not with attachments)
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title, username=ownership)

    # Get conversation history for context (exclude the just-added user message)
    conversation_history = conversation["messages"]  # History before current question

    # Run the 3-stage council process with full query including attachments
    images_for_council = image_attachments if image_attachments else None
    try:
        stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
            full_query,
            conversation_history,
            images=images_for_council,
            conversation_id=conversation_id  # For memory system
        )
    except ValueError as e:
        # Translate configuration errors (e.g., no council models) to 400
        raise HTTPException(status_code=400, detail=str(e))

    # Add assistant message with all stages and metadata
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result,
        metadata
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@router.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Send a message and stream the 3-stage council process. Requires authentication.
    Returns Server-Sent Events as each stage completes.
    Supports multimodal queries with image attachments.
    """
    # Check if conversation exists and is owned by current user
    ownership = _ownership_username(current_user)
    conversation = storage.get_conversation(conversation_id, username=ownership)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Separate image attachments from text attachments
    _, image_attachments = separate_attachments(request.attachments)

    # Build full query with text attachments only (images handled separately)
    full_query = build_query_with_attachments(request.content, request.attachments)

    # Get conversation history for context (before adding new message)
    conversation_history = conversation["messages"]

    # Get custom models and chairman from conversation (if set)
    conv_models = conversation.get("models")
    conv_chairman = conversation.get("chairman")
    execution_mode = (conversation.get("execution_mode") or "full").strip().lower()
    router_type = (conversation.get("router_type") or config.ROUTER_TYPE or "openrouter").strip().lower()
    if router_type not in {"openrouter", "ollama"}:
        router_type = config.ROUTER_TYPE
    if execution_mode not in {"chat_only", "chat_ranking", "full"}:
        execution_mode = "full"

    async def event_generator():
        # Initialize state variables OUTSIDE try block so finally can access them
        stage1_results = []
        stage2_results = []
        stage3_result = None
        tool_outputs = []
        label_to_model = {}
        aggregate_rankings = []
        message_saved = False  # Track if message was saved in normal flow
        title_task = None
        stage1_stream = None
        stage1_item_task = None
        stage2_task = None
        stage3_task = None

        try:
            # Reset token stats for this request
            reset_token_stats()

            # Add user message (store original content, not with attachments)
            storage.add_user_message(conversation_id, request.content)

            # Start title generation in parallel (don't await yet)
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content, router_type=router_type))

            # Stage 1: Collect responses with streaming - send each model's response as it completes
            # Pass images for multimodal queries
            stage1_start_time = time.time()
            yield f"data: {json.dumps({'type': 'stage1_start', 'timestamp': stage1_start_time})}\n\n"

            images_for_council = image_attachments if image_attachments else None
            # Determine web search provider (prefer explicit provider, fallback to legacy boolean)
            web_search_provider = (
                getattr(request, "web_search_provider", None)
                or ("tavily" if getattr(request, "web_search", False) else None)
            )

            try:
                stage1_stream = stage1_collect_responses_streaming(
                    full_query,
                    conversation_history,
                    conv_models,
                    images_for_council,
                    conversation_id,
                    web_search_provider=web_search_provider,
                    chairman=conv_chairman,
                    router_type=router_type,
                )
                while True:
                    if stage1_item_task is None:
                        stage1_item_task = asyncio.ensure_future(_next_stage1_item(stage1_stream))

                    # Do not use wait_for() here: timeout would cancel __anext__()
                    # and permanently close the Stage 1 async generator.
                    done, _ = await asyncio.wait(
                        {stage1_item_task},
                        timeout=STAGE1_HEARTBEAT_INTERVAL,
                    )
                    if not done:
                        elapsed = time.time() - stage1_start_time
                        if elapsed > config.STAGE1_TIMEOUT and stage1_results:
                            stage1_item_task.cancel()
                            await asyncio.gather(stage1_item_task, return_exceptions=True)
                            stage1_item_task = None
                            await stage1_stream.aclose()
                            stage1_stream = None

                            expected_models = len(conv_models or config.COUNCIL_MODELS)
                            dropped_count = max(expected_models - len(stage1_results), 0)
                            logger.warning(
                                "[STREAMING] Stage 1 timeout after %.1fs for conversation %s: "
                                "collected %d results, dropped %d pending models",
                                elapsed,
                                conversation_id,
                                len(stage1_results),
                                dropped_count,
                            )
                            yield f"data: {json.dumps({'type': 'stage1_timeout', 'collected': len(stage1_results), 'timestamp': time.time()})}\n\n"
                            break

                        yield f"data: {json.dumps({'type': 'heartbeat', 'stage': 'stage1', 'timestamp': time.time()})}\n\n"
                        continue

                    try:
                        item = stage1_item_task.result()
                    except StopAsyncIteration:
                        stage1_item_task = None
                        break
                    finally:
                        if stage1_item_task is not None and stage1_item_task.done():
                            stage1_item_task = None

                    # Handle tool_outputs message (first yield if tools were used)
                    if item.get("type") == "tool_outputs":
                        tool_outputs = item.get("tool_outputs", [])
                        yield f"data: {json.dumps({'type': 'tool_outputs', 'data': tool_outputs, 'timestamp': time.time()})}\n\n"
                    else:
                        # Send individual model response event
                        model_time = time.time()
                        yield f"data: {json.dumps({'type': 'stage1_model_response', 'data': item, 'timestamp': model_time})}\n\n"
                        stage1_results.append(item)
            except ValueError as e:
                # Configuration errors (e.g., no council models) - send error event and stop
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                return

            stage1_end_time = time.time()
            stage1_duration = stage1_end_time - stage1_start_time
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results, 'timestamp': stage1_end_time, 'duration': stage1_duration})}\n\n"

            # Execution mode: chat_only stops after Stage 1
            if execution_mode == "chat_only":
                token_stats = get_token_stats()
                metadata = {
                    "execution_mode": execution_mode,
                    "tool_outputs": tool_outputs,
                    "token_stats": token_stats,
                }
                storage.add_assistant_message(
                    conversation_id,
                    stage1_results,
                    None,
                    None,
                    metadata
                )
                message_saved = True

                if token_stats.get('total'):
                    yield f"data: {json.dumps({'type': 'token_stats', 'data': token_stats})}\n\n"

                if title_task:
                    title = await title_task
                    storage.update_conversation_title(conversation_id, title, username=ownership)
                    yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                return

            # Stage 2: Collect rankings with heartbeat to prevent CloudFront timeout
            stage2_start_time = time.time()
            yield f"data: {json.dumps({'type': 'stage2_start', 'timestamp': stage2_start_time})}\n\n"

            # Run Stage 2 with periodic heartbeats (CloudFront times out after ~30s without data)
            stage2_task = asyncio.create_task(
                stage2_collect_rankings(full_query, stage1_results, conv_models, router_type=router_type)
            )
            heartbeat_interval = 15  # Send heartbeat every 15 seconds
            heartbeat_count = 0
            while not stage2_task.done():
                try:
                    # Wait for task to complete OR timeout for heartbeat
                    await asyncio.wait_for(asyncio.shield(stage2_task), timeout=heartbeat_interval)
                except asyncio.TimeoutError:
                    # Task still running, send heartbeat to keep connection alive
                    heartbeat_count += 1
                    logger.info("[STREAMING] Sending Stage 2 heartbeat #%d", heartbeat_count)
                    yield f"data: {json.dumps({'type': 'heartbeat', 'stage': 'stage2', 'timestamp': time.time()})}\n\n"

            logger.info("[STREAMING] Stage 2 task finished, getting result...")
            try:
                stage2_results, label_to_model = stage2_task.result()
                logger.info("[STREAMING] Stage 2 got %d results", len(stage2_results))
            except Exception as task_error:
                logger.error("[STREAMING] Stage 2 task.result() raised: %s: %s", type(task_error).__name__, task_error)
                raise

            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            logger.info("[STREAMING] Rankings calculated: %d entries", len(aggregate_rankings))
            stage2_end_time = time.time()
            stage2_duration = stage2_end_time - stage2_start_time

            logger.info("[STREAMING] About to yield stage2_complete (%d results)", len(stage2_results))
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}, 'timestamp': stage2_end_time, 'duration': stage2_duration})}\n\n"
            logger.info("[STREAMING] Stage 2 complete yielded successfully, proceeding to Stage 3")

            # Execution mode: chat_ranking stops after Stage 2
            if execution_mode == "chat_ranking":
                token_stats = get_token_stats()
                metadata = {
                    "execution_mode": execution_mode,
                    "label_to_model": label_to_model,
                    "aggregate_rankings": aggregate_rankings,
                    "tool_outputs": tool_outputs,
                    "token_stats": token_stats,
                }
                storage.add_assistant_message(
                    conversation_id,
                    stage1_results,
                    stage2_results,
                    None,
                    metadata
                )
                message_saved = True

                if token_stats.get('total'):
                    yield f"data: {json.dumps({'type': 'token_stats', 'data': token_stats})}\n\n"

                if title_task:
                    title = await title_task
                    storage.update_conversation_title(conversation_id, title, username=ownership)
                    yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                return

            # Stage 3: Synthesize final answer with heartbeat
            stage3_start_time = time.time()
            logger.info("[STREAMING] Starting Stage 3")
            yield f"data: {json.dumps({'type': 'stage3_start', 'timestamp': stage3_start_time})}\n\n"

            # Run Stage 3 with periodic heartbeats
            stage3_task = asyncio.create_task(
                stage3_synthesize_final(
                    full_query,
                    stage1_results,
                    stage2_results,
                    conv_chairman,
                    tool_outputs=tool_outputs,
                    router_type=router_type,
                )
            )
            heartbeat_count = 0
            while not stage3_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(stage3_task), timeout=heartbeat_interval)
                except asyncio.TimeoutError:
                    heartbeat_count += 1
                    logger.info("[STREAMING] Sending Stage 3 heartbeat #%d", heartbeat_count)
                    yield f"data: {json.dumps({'type': 'heartbeat', 'stage': 'stage3', 'timestamp': time.time()})}\n\n"

            logger.info("[STREAMING] Stage 3 completed after %d heartbeats", heartbeat_count)
            stage3_result = stage3_task.result()
            stage3_end_time = time.time()
            stage3_duration = stage3_end_time - stage3_start_time

            # Get accumulated token stats from TOON encoding
            token_stats = get_token_stats()

            # CRITICAL FIX: Save assistant message IMMEDIATELY after stage3 completes
            # This ensures the message is saved even if client disconnects during streaming
            # Previously, save was at the end of generator which never executed on disconnect
            metadata = {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings, 'tool_outputs': tool_outputs, 'token_stats': token_stats}
            storage.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result,
                metadata
            )
            message_saved = True  # Mark as saved to prevent duplicate save in finally

            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result, 'timestamp': stage3_end_time, 'duration': stage3_duration})}\n\n"

            # Send token stats event (TOON encoding savings)
            if token_stats.get('total'):
                yield f"data: {json.dumps({'type': 'token_stats', 'data': token_stats})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title, username=ownership)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except asyncio.CancelledError:
            # Client disconnected - re-raise to allow proper generator cleanup
            # The finally block below will save partial results
            logger.info("[STREAMING] Client disconnected (CancelledError) during streaming for conversation %s", conversation_id)
            raise
        except GeneratorExit:
            # Generator closed by consumer (client disconnected)
            # This is the more common case for SSE client disconnection
            logger.info("[STREAMING] Client disconnected (GeneratorExit) during streaming for conversation %s", conversation_id)
            raise
        except Exception as e:
            logger.error("[STREAMING] Exception during streaming for conversation %s: %s: %s", conversation_id, type(e).__name__, str(e))
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        except BaseException as e:
            # Catch ALL exceptions including SystemExit, KeyboardInterrupt, etc.
            # to understand what's causing the generator to stop
            logger.error("[STREAMING] BaseException during streaming for conversation %s: %s: %s", conversation_id, type(e).__name__, str(e))
            raise
        finally:
            # Best-effort: cancel any in-flight tasks on disconnect/abort.
            tasks_to_cleanup = [
                t for t in (title_task, stage1_item_task, stage2_task, stage3_task)
                if t is not None and not t.done()
            ]
            for task in tasks_to_cleanup:
                task.cancel()
            # Await cancelled tasks to prevent "task was destroyed but pending" warnings
            # Use shield to protect cleanup from cancellation, and handle CancelledError
            # (which is a BaseException in Python 3.8+, not caught by except Exception)
            if tasks_to_cleanup:
                try:
                    await asyncio.shield(asyncio.gather(*tasks_to_cleanup, return_exceptions=True))
                except asyncio.CancelledError:
                    pass  # Cleanup was interrupted by cancellation, tasks are already cancelled
                except Exception:
                    pass  # Ignore other cleanup errors

            if stage1_stream is not None:
                try:
                    await stage1_stream.aclose()
                except Exception:
                    pass

            # CRITICAL FIX: Save partial results if client disconnected before completion
            # This ensures we don't lose work when client closes connection mid-stream
            if not message_saved and stage1_results:
                logger.info("[STREAMING] Saving partial results for conversation %s (stage1=%d, stage2=%d, stage3=%s)", conversation_id, len(stage1_results), len(stage2_results), 'yes' if stage3_result else 'no')
                partial_metadata = {
                    'label_to_model': label_to_model,
                    'aggregate_rankings': aggregate_rankings,
                    'tool_outputs': tool_outputs,
                    'partial': True,  # Mark as partial results
                    'stages_completed': {
                        'stage1': len(stage1_results) > 0,
                        'stage2': len(stage2_results) > 0,
                        'stage3': stage3_result is not None
                    }
                }
                try:
                    storage.add_assistant_message(
                        conversation_id,
                        stage1_results,
                        stage2_results,
                        stage3_result,
                        partial_metadata
                    )
                    logger.info("[STREAMING] Partial results saved successfully for conversation %s", conversation_id)
                except Exception as save_error:
                    logger.error("[STREAMING] Failed to save partial results: %s", save_error)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream; charset=utf-8",
            "X-Accel-Buffering": "no",  # Disable nginx buffering for real-time SSE
        }
    )
