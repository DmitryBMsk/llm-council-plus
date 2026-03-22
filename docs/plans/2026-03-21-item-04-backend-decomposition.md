# Item 04: Backend API and Streaming Decomposition

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce change risk in the backend by extracting route modules and moving long streaming orchestration out of `backend/main.py`.

**Architecture:** Separate HTTP concerns from orchestration concerns. Route modules should validate request/response boundaries, while services should own conversation operations, stage sequencing, and partial-save/disconnect behavior.

**Tech Stack:** FastAPI routers, async generators, pytest.

---

## Design

### Problem

- `backend/main.py` is too large and mixes setup, auth, settings, conversation CRUD, uploads, streaming, and Drive endpoints.
- `send_message_stream()` is long and behavior-dense.
- This raises review cost and makes behavioral regressions likely.

### Design Decisions

- Extract routes without changing public API paths.
- Preserve SSE event contract exactly during refactor.
- Move orchestration first, then route registration; do not attempt a full domain redesign in one item.

### Files

- Create: `backend/api/routes/conversations.py`
- Create: `backend/api/routes/setup.py`
- Create: `backend/api/routes/settings.py`
- Create: `backend/api/routes/auth.py`
- Create: `backend/api/routes/uploads.py`
- Create: `backend/api/routes/drive.py`
- Create: `backend/services/conversation_service.py`
- Create: `backend/services/streaming_service.py`
- Modify: `backend/main.py`
- Modify: `backend/council.py`
- Test: `backend/tests/test_streaming_disconnect.py`
- Test: `backend/tests/test_execution_modes.py`

### Risks

- SSE event order and disconnect semantics are easy to break.
- Title-generation timing can regress silently.
- Import cycles may appear during extraction.
- If auth/upload/drive routes remain in `backend/main.py`, the refactor goal should be considered incomplete.

### Local E2E Gate

1. Start stack locally.
2. Create conversation.
3. Send streaming message.
4. Observe stage transitions.
5. Abort in-flight request.
6. Reload conversation and verify partial or final persistence is still correct.

## Implementation

### Task 1: Freeze current behavior with tests

**Files:**
- Modify: `backend/tests/test_streaming_disconnect.py`
- Modify: `backend/tests/test_execution_modes.py`

**Step 1: Extend tests**

- Cover:
  - disconnect partial-save behavior
  - title generation for first message
  - heartbeat events
  - mode-specific stop points (`chat_only`, `chat_ranking`, `full`)
  - `tool_outputs`
  - `token_stats`
  - `title_complete`
  - `error`
  - heartbeat ordering
  - partial-save metadata shape

**Step 2: Run targeted tests**

Run: `./.venv/bin/python -m pytest backend/tests/test_streaming_disconnect.py backend/tests/test_execution_modes.py -q`

Expected: PASS before refactor

### Task 2: Extract streaming/conversation services

**Files:**
- Create: `backend/services/conversation_service.py`
- Create: `backend/services/streaming_service.py`
- Modify: `backend/main.py`

**Step 1: Minimal implementation**

- Move conversation mutations and title-generation coordination into services.
- Move SSE orchestration into a service that yields structured events.

**Step 2: Re-run targeted tests**

Run: `./.venv/bin/python -m pytest backend/tests/test_streaming_disconnect.py backend/tests/test_execution_modes.py -q`

Expected: PASS

### Task 3: Extract route modules

**Files:**
- Create: `backend/api/routes/conversations.py`
- Create: `backend/api/routes/setup.py`
- Create: `backend/api/routes/settings.py`
- Create: `backend/api/routes/auth.py`
- Create: `backend/api/routes/uploads.py`
- Create: `backend/api/routes/drive.py`
- Modify: `backend/main.py`

**Step 1: Minimal implementation**

- Register routers in `backend/main.py`.
- Keep paths and response contracts unchanged.
- Reduce `backend/main.py` to composition/bootstrap rather than a mixed route implementation file.

**Step 2: Re-run broader checks**

Run: `./.venv/bin/python -m pytest -q`

Expected: PASS

### Task 4: Verification, review, commit

**Step 1: Run local E2E gate**

- docker compose up
- streaming send
- stop/abort
- reload conversation state

**Step 2: External agent review**

- Ask the second coding agent to review SSE compatibility, disconnect cleanup, and route/service boundary quality.

**Step 3: Commit**

```bash
git add backend/api/routes backend/services backend/main.py backend/council.py backend/tests/test_streaming_disconnect.py backend/tests/test_execution_modes.py
git commit -m "refactor: split backend routes and streaming services"
```
