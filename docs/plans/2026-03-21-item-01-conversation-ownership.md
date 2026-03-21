# Item 01: Conversation Ownership Enforcement

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enforce per-user ownership on conversation CRUD and message routes so authenticated users cannot access each other’s data.

**Architecture:** Keep ownership checks server-side and close to the storage boundary. Route handlers should always pass `current_user`, and storage should expose username-scoped read/update/delete APIs for both JSON and DB backends.

**Tech Stack:** FastAPI, pytest, SQLAlchemy/JSON storage.

---

## Design

### Problem

- Auth exists, but conversation endpoints do not enforce ownership.
- Storage public APIs are not username-aware.
- This creates a cross-user data isolation bug when `AUTH_ENABLED=true`.

### Design Decisions

- Treat unauthorized access as `404` rather than `403` to avoid conversation ID enumeration.
- Make username scoping explicit in storage public functions rather than sprinkling inline checks in route handlers.
- Preserve `guest` behavior for auth-disabled mode.
- Define legacy ownership policy up front:
  - when `AUTH_ENABLED=false`, request identity remains `guest`, so ownerless legacy conversations remain reachable through `guest` behavior
  - when `AUTH_ENABLED=true`, ownerless conversations are not exposed to named users
  - `delete_all_conversations()` becomes user-scoped in auth-enabled mode and preserves current guest/global semantics in auth-disabled mode

### Files

- Modify: `backend/main.py`
- Modify: `backend/storage.py`
- Modify: `backend/models.py`
- Test: `backend/tests/test_conversation_authorization.py`

### Risks

- Existing tests may assume unscoped storage helpers.
- Old conversations may have missing `username`; this item intentionally treats them as unavailable to named users once auth is enabled.
- `delete_all_conversations()` semantics must change without surprising auth-disabled mode.

### Local E2E Gate

1. Start stack locally with auth enabled.
2. Create two users.
3. Login as user A and create a conversation.
4. Login as user B.
5. Verify user B cannot list, fetch, rename, delete, or send messages to user A’s conversation.
6. Verify user A still can use the conversation normally.

## Implementation

### Task 1: Add failing authorization tests

**Files:**
- Create: `backend/tests/test_conversation_authorization.py`

**Step 1: Write the failing test**

- Add tests for:
  - scoped list
  - scoped get
  - scoped rename
  - scoped delete
  - scoped delete-all
  - scoped message send / stream
  - ownerless legacy conversation behavior under auth-disabled vs auth-enabled assumptions

**Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_conversation_authorization.py -q`

Expected: FAIL

### Task 2: Add username scoping to storage public APIs

**Files:**
- Modify: `backend/storage.py`
- Modify: `backend/models.py`

**Step 1: Minimal implementation**

- Add username-aware signatures for:
  - `list_conversations`
  - `get_conversation`
  - `update_conversation_title`
  - `delete_conversation`
  - `delete_all_conversations`
- Scope DB reads/writes by `Conversation.username`.
- Scope JSON reads/writes by loaded conversation metadata.
- Preserve:
  - auth-disabled `guest` access to guest/legacy conversations
  - auth-enabled isolation from ownerless legacy records

**Step 2: Re-run focused test**

Run: `./.venv/bin/python -m pytest backend/tests/test_conversation_authorization.py -q`

Expected: still FAIL or partially pass until routes are updated.

### Task 3: Wire ownership through route handlers

**Files:**
- Modify: `backend/main.py`

**Step 1: Minimal implementation**

- Pass `current_user` into every conversation route and message route.
- Return `404` on owner mismatch.

**Step 2: Re-run focused test**

Run: `./.venv/bin/python -m pytest backend/tests/test_conversation_authorization.py -q`

Expected: PASS

### Task 4: Broader verification and review gate

**Step 1: Run broader backend regression**

Run: `./.venv/bin/python -m pytest -q`

Expected: PASS

**Step 2: Run local E2E gate**

Run:
- `docker compose up -d --build`
- auth-enabled two-user scenario via browser/API smoke
- verify `delete_all_conversations()` only removes the current user’s records

Expected: user separation works end to end.

**Step 3: External agent review**

- Send the diff to a fresh coding agent with explicit focus on authorization bypasses and missing tests.

**Step 4: Commit**

```bash
git add backend/main.py backend/storage.py backend/models.py backend/tests/test_conversation_authorization.py
git commit -m "fix: enforce conversation ownership"
```
