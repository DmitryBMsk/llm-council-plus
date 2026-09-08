"""Explicit, single-model continuation. Never edits the original council result."""

import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path as ApiPath
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ... import attachments, config, storage, router_dispatch, runtime_settings
from ...council import _usage_fields, parse_ranking_from_text, build_context_prompt
from ...usage import get_provider_usage
from ...run_context import active_ticket
from ...run_routes import managed_run
from ..deps import get_current_user, _ownership_username

router = APIRouter(tags=["conversations"])
UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
_LIMIT_REASONS = {"length", "max_tokens", "max_output_tokens", "model_length"}


class ContinueResponseRequest(BaseModel):
    message_index: int = Field(ge=0)
    stage: Literal["stage1", "stage2", "stage3"]
    model: str = Field(min_length=1, max_length=255)
    request_id: str = Field(pattern=UUID_PATTERN)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _source(conversation, request):
    messages = conversation.get("messages", [])
    if request.message_index >= len(messages) or messages[request.message_index].get("role") != "assistant":
        raise HTTPException(422, "Choose an existing assistant response")
    message = messages[request.message_index]
    rows = message.get(request.stage) or []
    rows = rows if isinstance(rows, list) else [rows]
    row = next((row for row in rows if row.get("model") == request.model), None)
    if row is None:
        raise HTTPException(404, "Selected model response not found")
    reasons = [str(row.get(key) or "").lower() for key in ("finish_reason", "native_finish_reason")]
    limited = row.get("truncated") is True or any(reason in _LIMIT_REASONS for reason in reasons)
    # Historical responses lack stop metadata: allow an explicit, labelled retry
    # when usage reaches the old cap, never rewrite them as definitely truncated.
    legacy = not any(reasons) and row.get("truncated") is not False
    usage = row.get("usage") or {}
    suspected = legacy and usage.get("completion_tokens", 0) >= (row.get("effective_max_tokens") or 8192)
    if not limited and not suspected:
        raise HTTPException(409, "This response is not marked as token-limited")
    return message, row, not limited


def _root_source_index(conversation, index):
    """Follow append-only continuation links to the original model response."""
    while True:
        parent = (conversation["messages"][index].get("metadata") or {}).get("continuation_of")
        if not parent:
            return index
        previous = parent.get("message_index")
        if not isinstance(previous, int) or not 0 <= previous < index:
            raise HTTPException(409, "Invalid continuation history; reload the conversation")
        index = previous


def _provider_failure(message):
    ticket = active_ticket.get()
    return HTTPException(
        502,
        {
            "code": "continuation_failed",
            "message": message,
            "status": "failed",
            "run_id": ticket.run_id if ticket else None,
        },
    )


def _original_question(conversation, index):
    for user_index in range(index - 1, -1, -1):
        message = conversation["messages"][user_index]
        if message.get("role") == "user":
            text = message.get("content", "")
            for attachment in message.get("attachments", []):
                if attachment.get("file_type") != "image" and attachment.get("content"):
                    text += f"\n\nAttached extracted text ({attachment.get('filename', 'document')}):\n{attachment['content']}"
            return build_context_prompt(conversation["messages"][:user_index], text)
    return "Continue the selected response."


def _persist_pair(conversation_id, username, source_index, source_fingerprint, result, label):
    def update(conversation):
        if not storage._owner_matches(conversation.get("username"), username):
            raise ValueError("Conversation not found")
        ticket = active_ticket.get()
        if ticket is not None:
            ticket.ensure_active()
        if (
            source_index >= len(conversation["messages"])
            or _fingerprint(conversation["messages"][source_index]) != source_fingerprint
        ):
            raise ValueError("Original response changed; reload before continuing")
        conversation["messages"].append(
            {"role": "user", "content": label, "continuation_of": result["metadata"]["continuation_of"]}
        )
        assistant = {"role": "assistant", "metadata": result["metadata"]}
        assistant.update(
            {stage: result[stage] for stage in ("stage1", "stage2", "stage3") if result.get(stage) is not None}
        )
        conversation["messages"].append(assistant)

    if storage.is_using_database():
        storage._db_update_conversation(conversation_id, update, username=username)
    else:
        storage._json_update_conversation(conversation_id, update)


@router.post("/api/conversations/{conversation_id}/continue")
@managed_run()
async def continue_response(
    conversation_id: Annotated[str, ApiPath(pattern=UUID_PATTERN)],
    request: ContinueResponseRequest,
    current_user: str = Depends(get_current_user),
):
    ownership = _ownership_username(current_user)
    conversation = await run_in_threadpool(storage.get_conversation, conversation_id, username=ownership)
    if conversation is None:
        raise HTTPException(404, "Conversation not found")
    source_message, source, suspected = _source(conversation, request)
    fingerprint = _fingerprint(source_message)
    prefix = source.get("ranking" if request.stage == "stage2" else "response") or ""
    root_index = _root_source_index(conversation, request.message_index)
    root_message = conversation["messages"][root_index]
    question = _original_question(conversation, root_index)
    evidence = (root_message.get("metadata") or {}).get("tool_outputs")
    if evidence:
        question += "\n\nOriginal tool evidence:\n" + json.dumps(evidence, ensure_ascii=False)
    # Reference stages supply grounding for ranking/synthesis continuation, not
    # new evaluations. No other model/stage is run automatically.
    if request.stage != "stage1":
        references = {
            stage: root_message.get(stage)
            for stage in ("stage1", "stage2")
            if stage != request.stage and root_message.get(stage)
        }
        references["label_to_model"] = (root_message.get("metadata") or {}).get("label_to_model", {})
        question += "\n\nOriginal council context:\n" + json.dumps(references, ensure_ascii=False)
    if len(question) + len(prefix) > 500_000:
        raise HTTPException(422, "Continuation context is too large; use a shorter focused follow-up")
    router_type = conversation.get("router_type") or config.ROUTER_TYPE
    images = []
    if request.stage == "stage1":
        original_history = {**conversation, "messages": conversation["messages"][:root_index]}
        try:
            images = await run_in_threadpool(attachments.latest_images, original_history)
        except (OSError, ValueError) as error:
            raise HTTPException(409, "Original image unavailable; reattach it before continuing") from error
        if images and router_type == "ollama":
            raise HTTPException(400, "Ollama image continuation is not supported")
    messages = []
    if conversation.get("system_prompt"):
        messages.append({"role": "system", "content": conversation["system_prompt"]})
    messages.append(
        {"role": "user", "content": router_dispatch.build_message_content(router_type, question, images or None)}
    )
    if prefix:
        messages.append({"role": "assistant", "content": prefix})
    task = {
        "stage1": "If no visible answer was produced, answer the original question now.",
        "stage2": "Continue evaluating and ranking the original council responses, not answering the question again. "
        "Use the supplied label_to_model mapping. End with FINAL RANKING: followed by numbered "
        "Response labels, one per line. If no visible evaluation was produced, write the evaluation and ranking now.",
        "stage3": "Continue the chairman synthesis of the original council responses and peer rankings. "
        "If no visible answer was produced, synthesize the final council answer now.",
    }[request.stage]
    messages.append(
        {
            "role": "user",
            "content": "Your previous response reached its output limit. Continue exactly from where it ended. "
            "Return only the missing continuation, do not repeat the existing text or add a preamble. "
            "If it ended inside a word, complete that word. Preserve the language and formatting. " + task,
        }
    )
    settings = await run_in_threadpool(runtime_settings.get_runtime_settings)
    temperature = {
        "stage1": settings.council_temperature,
        "stage2": settings.stage2_temperature,
        "stage3": settings.chairman_temperature,
    }[request.stage]
    answer = await router_dispatch.query_model(
        router_type, model=request.model, messages=messages, stage="CONTINUATION", temperature=temperature
    )
    if not answer or answer.get("error"):
        raise _provider_failure((answer or {}).get("error_message") or "Continuation provider failed")
    text = answer.get("content") or ""
    if not text and not answer.get("truncated"):
        raise _provider_failure("The model returned no continuation text")
    row = {"model": request.model, **_usage_fields(answer)}
    row["ranking" if request.stage == "stage2" else "response"] = prefix + text
    if request.stage == "stage2":
        row["parsed_ranking"] = parse_ranking_from_text(row["ranking"])
    result = {
        "stage1": [],
        "stage2": None,
        "stage3": None,
        "metadata": {
            "continuation_of": {
                "message_index": request.message_index,
                "stage": request.stage,
                "model": request.model,
                "legacy_suspected": suspected,
            },
            "continuation": True,
            "original_rankings_unchanged": True,
        },
    }
    ticket = active_ticket.get()
    result["metadata"].update(provider_usage=get_provider_usage())
    if ticket is not None:
        result["metadata"].update(run_id=ticket.run_id, request_id=ticket.request_id)
    result[request.stage] = row if request.stage == "stage3" else [row]
    if request.stage == "stage2":
        result["metadata"]["label_to_model"] = source_message.get("metadata", {}).get("label_to_model", {})
    try:
        await run_in_threadpool(
            _persist_pair,
            conversation_id,
            ownership,
            request.message_index,
            fingerprint,
            result,
            f"Continue {request.model} ({request.stage}); original council results unchanged.",
        )
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return result
