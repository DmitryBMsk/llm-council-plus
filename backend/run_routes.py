"""Admission, recovery and accounting shared by HTTP and SSE council routes."""

from functools import wraps
import asyncio
from uuid import uuid4
import json

import anyio
from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from . import config, storage
from .api.deps import get_current_user, _ownership_username
from .run_control import RunControl, RunRejected
from .run_context import active_ticket
from .usage import begin_provider_usage, end_provider_usage, get_provider_usage


class ManagedStreamingResponse(StreamingResponse):
    """Close nested generators in the task that iterated them, even on disconnect."""

    def __init__(self, *args, ticket, **kwargs):
        super().__init__(*args, **kwargs)
        self.ticket = ticket

    async def stream_response(self, send):
        try:
            await super().stream_response(send)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await self.body_iterator.aclose()
                finally:
                    await run_in_threadpool(self.ticket.close)


def validate_models(models):
    if models is not None and (
        not 1 <= len(models) <= config.MAX_COUNCIL_MODELS
        or len(set(models)) != len(models)
        or any(not isinstance(m, str) or not m.strip() or len(m) > 255 for m in models)
    ):
        raise ValueError(f"Models must be unique, nonempty and at most {config.MAX_COUNCIL_MODELS}")
    return models


def _event(payload, ticket):
    return "data: " + json.dumps({**payload, "run_id": ticket.run_id, "request_id": ticket.request_id}) + "\n\n"


async def _replay(ticket):
    result = ticket.result or {}
    for stage in ("stage1", "stage2", "stage3"):
        if result.get(stage) is not None:
            yield _event(
                {"type": stage + "_complete", "data": result[stage], "metadata": result.get("metadata", {})}, ticket
            )
    if ticket.status == "partial":
        yield _event({"type": "error", "message": "Recovered partial result; start a new request to continue."}, ticket)
    else:
        yield _event({"type": "complete"}, ticket)


def managed_run(*, streaming=False):
    def decorate(operation):
        @wraps(operation)
        async def wrapped(conversation_id, request, current_user=Depends(get_current_user)):
            if streaming and getattr(request, "temporary", False):
                raise HTTPException(422, "Temporary mode is supported only by the non-stream endpoint")
            temporary = bool(getattr(request, "temporary", False)) and not streaming
            conversation = (
                None
                if temporary
                else await run_in_threadpool(
                    storage.get_conversation, conversation_id, username=_ownership_username(current_user)
                )
            )
            if not temporary and conversation is None:
                raise HTTPException(404, "Conversation not found")
            models = (conversation or {}).get("models") or config.COUNCIL_MODELS
            try:
                validate_models(models)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            payload = request.model_dump(exclude={"request_id"})
            payload.update(
                models=models,
                router_type=(conversation or {}).get("router_type") or config.ROUTER_TYPE,
                chairman=(conversation or {}).get("chairman"),
                system_prompt=(conversation or {}).get("system_prompt"),
                execution_mode=(conversation or {}).get("execution_mode"),
            )
            try:
                control = await run_in_threadpool(RunControl)
                ticket = await run_in_threadpool(
                    control.acquire,
                    user=current_user,
                    conversation_id=(
                        f"temporary:{current_user}:{getattr(request, 'request_id', None) or uuid4()}"
                        if temporary
                        else conversation_id
                    ),
                    request_id=getattr(request, "request_id", None),
                    payload=payload,
                )
            except RunRejected as error:
                headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
                raise HTTPException(
                    error.status_code,
                    {"code": error.code, "message": str(error), "run_id": error.run_id, "status": error.status},
                    headers=headers,
                ) from error
            if ticket.replayed:
                if ticket.result is None:
                    raise HTTPException(
                        409,
                        {
                            "code": "result_not_retained",
                            "run_id": ticket.run_id,
                            "message": "Run completed but its result is not retained; no new work was started",
                        },
                    )
                return (
                    StreamingResponse(_replay(ticket), media_type="text/event-stream") if streaming else ticket.result
                )
            if not streaming:
                usage_token = begin_provider_usage()
                run_token = active_ticket.set(ticket)
                try:
                    result = await operation(conversation_id, request, current_user=current_user)
                    await run_in_threadpool(ticket.ensure_active)
                    usage = get_provider_usage()
                    if getattr(request, "request_id", None):
                        result = {
                            **result,
                            "metadata": {
                                **result.get("metadata", {}),
                                "run_id": ticket.run_id,
                                "request_id": ticket.request_id,
                                "provider_usage": usage,
                            },
                        }
                    await run_in_threadpool(ticket.complete, None if temporary else result, usage=usage)
                    return result
                except BaseException as error:
                    with anyio.CancelScope(shield=True):
                        if ticket.status == "running":
                            try:
                                await run_in_threadpool(
                                    ticket.fail,
                                    status="aborted" if isinstance(error, asyncio.CancelledError) else "failed",
                                    usage=get_provider_usage(),
                                )
                            except RuntimeError:
                                pass
                    raise
                finally:
                    with anyio.CancelScope(shield=True):
                        await run_in_threadpool(ticket.close)
                    active_ticket.reset(run_token)
                    end_provider_usage(usage_token)
            try:
                response = await operation(conversation_id, request, current_user=current_user)
            except BaseException:
                with anyio.CancelScope(shield=True):
                    await run_in_threadpool(ticket.close)
                raise

            async def events():
                usage_token = begin_provider_usage()
                run_token = active_ticket.set(ticket)
                result = {
                    "stage1": [],
                    "stage2": None,
                    "stage3": None,
                    "metadata": {"execution_mode": (conversation or {}).get("execution_mode") or "full"},
                }
                had_error = False
                try:
                    async for chunk in response.body_iterator:
                        await run_in_threadpool(ticket.ensure_active)
                        raw = chunk.decode() if isinstance(chunk, bytes) else chunk
                        for line in raw.splitlines():
                            if not line.startswith("data: "):
                                continue
                            event = json.loads(line[6:])
                            kind = event.get("type")
                            had_error = had_error or kind == "error"
                            if kind in ("stage1_complete", "stage2_complete", "stage3_complete"):
                                result[kind[:6]] = event.get("data")
                                result["metadata"].update(event.get("metadata") or {})
                            elif kind == "stage1_model_response" and event.get("data"):
                                result["stage1"].append(event["data"])
                            if kind == "tool_outputs":
                                result["metadata"]["tool_outputs"] = event.get("data")
                            if kind == "token_stats":
                                result["metadata"]["token_stats"] = event.get("data")
                            if kind == "complete":
                                result["metadata"].update(
                                    run_id=ticket.run_id,
                                    request_id=ticket.request_id,
                                    provider_usage=get_provider_usage(),
                                )
                                await run_in_threadpool(ticket.complete, result, usage=get_provider_usage())
                                event["metadata"] = result["metadata"]
                            yield _event(event, ticket)
                finally:
                    with anyio.CancelScope(shield=True):
                        await response.body_iterator.aclose()
                        if ticket.status == "running" and result["stage1"]:
                            result["metadata"].update(
                                partial=True,
                                run_id=ticket.run_id,
                                request_id=ticket.request_id,
                                provider_usage=get_provider_usage(),
                            )
                            try:
                                await run_in_threadpool(
                                    ticket.fail, status="partial", result=result, usage=get_provider_usage()
                                )
                            except RuntimeError:
                                pass  # expired lease may not publish a late result
                        if ticket.status == "running":
                            try:
                                await run_in_threadpool(
                                    ticket.fail, status="failed" if had_error else "aborted", usage=get_provider_usage()
                                )
                            except RuntimeError:
                                pass
                        await run_in_threadpool(ticket.close)
                    active_ticket.reset(run_token)
                    end_provider_usage(usage_token)

            return ManagedStreamingResponse(
                events(),
                ticket=ticket,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type="text/event-stream",
                background=BackgroundTask(ticket.close),
            )

        return wrapped

    return decorate
