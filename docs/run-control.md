# Run admission and provider usage

`backend.run_control` is a synchronous service. Async API routes must invoke it
in a threadpool, before saving a user message or starting any model request.

```python
control = RunControl()
ticket = control.acquire(
    user=current_user,
    conversation_id=conversation_id,
    request_id=request_id,  # UUID string; None generates a new request ID
    payload={"message": text, "models": models, "attachments": attachments},
)
try:
    if ticket.replayed:
        return ticket.result
    ticket.ensure_active()  # before each subsequent paid stage
    result = execute_and_persist_response()
    ticket.complete(result, usage=attributed_usage)
    return result
finally:
    ticket.close()
```

The async streaming route must acquire before returning StreamingResponse, retain
its ticket through stream generation and close in the generator's finally block.
Also arrange cleanup if a disconnect prevents the generator from starting.
`RunRejected` exposes `status_code`, `code`, `run_id`, `status` and `retry_after`.
Use 409 for duplicate/conflicting/conversation-busy requests and 429 plus
`Retry-After` for admission/rate limits. Return the request/run ID to clients.
Check conversation ownership before admission/replay. In shared mode, use `guest`.

Request identity is `(user, request_id)`. A SHA-256 digest includes conversation ID
and the canonical JSON payload. Include all inputs affecting execution, such as
router, mode, models, system prompt and attachments. A changed payload under an
existing ID returns 409. A completed or partial request returns its durable result
without consuming another quota slot; failed/aborted/running requests return 409.
The caller must deliberately choose a new ID for a new attempt after failure.
Use `ticket.fail(status="partial", result=..., usage=...)` after persisting partial
results, or `failed`/`aborted` when no usable result exists. `close()` aborts unfinished
work and is idempotent. No request-ID records are automatically deleted.

## Limits and persistence

| Environment variable | Default |
| --- | --- |
| `RUN_CONTROL_DB` | `Path(DATA_DIR).parent / "run_control.sqlite3"` |
| `RUN_MAX_ACTIVE` | 8 |
| `RUN_MAX_USER_ACTIVE` | 2 |
| `RUN_RATE_REQUESTS` | 20 |
| `RUN_RATE_WINDOW_SECONDS` | 60 |
| `RUN_LEASE_SECONDS` | 120 |

`MAX_COUNCIL_MODELS` also bounds the `payload.models` list. The API must reject
empty/duplicate/excessive models at creation and request boundaries as well.
Rate windows count admitted runs, including failed attempts, not rejected requests
or idempotent replays. One conversation may have at most one running request,
regardless of user. Invalid zero/negative configuration fails closed.

SQLite `BEGIN IMMEDIATE` protects admission across processes. All workers must use
the same DB on a local volume supporting SQLite locks; this is not a distributed
multi-host quota service. Persist the DB alongside conversation data and restrict
its permissions like other application data: cached results may contain user text.

Each fresh ticket starts one heartbeat thread, bounded by active-run limits,
renewing every lease/3 seconds. Completion/close stops it. Process death stops
renewal; after expiry, a new request can acquire capacity. The old request retains
its aborted idempotency record. Lease checks fence late result publication; they
cannot undo a provider request already sent before a process crash. In particular,
application-storage writes and run completion are not one distributed transaction:
a crash between them yields an aborted ID requiring deliberate recovery/new ID,
never automatic repeated paid execution under the same ID.

## Usage contract

Provider responses optionally include `usage`. OpenRouter preserves the nonempty
provider usage object, including token breakdowns and provider-reported cost.
Ollama normalizes `prompt_eval_count` and `eval_count` to `prompt_tokens` and
`completion_tokens`; `total_tokens` is their sum only when both exist. Missing
usage stays absent and must not be displayed as zero cost.

Keep usage beside each Stage 1/Stage 2/chairman response and pass an attributed list
(e.g. `{stage, model, router_type, usage}`) to `ticket.complete` or `ticket.fail`.
Capture usage for every actual attempt, including fallback and title generation,
when calculating total run spend. TOON savings are not provider billing. This
module does not estimate unavailable prices or promise a monetary hard budget.

References checked through Context7:
- https://github.com/openrouterteam/docs/blob/main/cookbook/administration/usage-accounting.mdx
- https://github.com/ollama/ollama/blob/main/docs/api.md

## HTTP integration and privacy

Both message endpoints accept optional UUID `request_id`; the browser generates one per submission. A matching completed retry replays without invoking a provider or appending another message. Active/conflicting/failed/aborted retries are explicit 409 responses. Partial replies are replayed with an interruption notice; there is no automatic paid retry.

Temporary mode is supported only by the non-stream endpoint. It stores a digest/idempotency tombstone and usage, never the reply; a repeat cannot regenerate a discarded answer silently. Temporary runs use their own namespace. Deleting a conversation fences active runs and removes cached replies, including the window during deletion. Digest tombstones and non-content usage remain to prevent duplicate paid work.

SSE cleanup closes nested generators in the same task before releasing the run lease, including disconnect before response headers. Failed/cancelled attempts retain observed usage; missing provider usage/cost remains unknown. Limits are shared only by workers using the same `RUN_CONTROL_DB` local volume; this is not a distributed multi-host quota service.

## Resource limits

- `MAX_REQUEST_BODY_BYTES`: default 40 MiB; enforced before JSON/multipart parsing, including chunked uploads. Large responses are not limited.
- PDF parsing: two concurrent disposable workers per API process; excess gets 429. `PDF_MAX_PAGES` defaults to 100; `PDF_PARSE_TIMEOUT_SECONDS` defaults to 20. Workers are killed/reaped on timeout and return at most 50,000 extracted characters. Linux workers have a 1 GiB virtual-memory limit; Unix CPU limit applies. macOS/Windows do not have the same memory guarantee. Size the container/host budget for API plus concurrent workers.
- `DATA_DIR/attachments` stores image binaries and must be included in persistent volumes/backups, including SQL deployments.
