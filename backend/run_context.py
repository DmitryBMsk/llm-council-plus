"""Active durable run lease propagated through provider child tasks."""
from contextvars import ContextVar
from starlette.concurrency import run_in_threadpool

active_ticket = ContextVar('active_run_ticket', default=None)


async def ensure_run_active():
    ticket = active_ticket.get()
    if ticket is not None:
        await run_in_threadpool(ticket.ensure_active)
