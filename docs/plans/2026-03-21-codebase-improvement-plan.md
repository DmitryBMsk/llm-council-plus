# Codebase Improvement Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate the highest-risk security and correctness issues, then reduce architectural concentration and add durable quality gates for backend and frontend development.

**Architecture:** Start with isolation/security fixes that preserve existing product behavior, then refactor around clear seams: request-scoped authorization, typed settings, service-layer streaming orchestration, and smaller frontend stateful hooks/components. Defer non-critical polish until correctness and testability are improved.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy/JSON storage, React + Vite + Zustand, pytest, ESLint.

**Priority Order:** Execute Task 1 and Task 2 before any feature work. Tasks 3-6 can proceed after the security baseline is restored.

---

### Task 1: Enforce conversation ownership and multi-user isolation

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/storage.py`
- Modify: `backend/models.py`
- Test: `backend/tests/test_conversation_authorization.py`

**Step 1: Write failing authorization tests**

- Add tests that prove:
  - `list_conversations()` only returns the current user’s conversations
  - `GET /api/conversations/{id}` returns `404` or `403` for another user’s conversation
  - `PATCH /api/conversations/{id}/title` cannot rename another user’s conversation
  - `DELETE /api/conversations/{id}` cannot delete another user’s conversation
  - `DELETE /api/conversations` deletes only the current user’s conversations
  - `POST /api/conversations/{id}/message` and `/message/stream` reject access to another user’s conversation

**Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/tests/test_conversation_authorization.py -q`

Expected: FAIL because storage and route handlers do not currently scope by `username`.

**Step 3: Minimal implementation**

- Change storage entrypoints to accept `username` where ownership matters:
  - `list_conversations(username: str)`
  - `get_conversation(conversation_id: str, username: str | None = None)`
  - `delete_conversation(conversation_id: str, username: str | None = None)`
  - `update_conversation_title(conversation_id: str, title: str, username: str | None = None)`
  - `delete_all_conversations(username: str | None = None)`
- Filter both JSON and DB backends by `username`.
- Keep `AUTH_ENABLED=false` behavior simple by using `guest` consistently.
- Update every conversation route in `backend/main.py` to pass `current_user`.
- Preserve the existing response contract where practical; treat unauthorized access as “not found” if you want to avoid ID enumeration.

**Step 4: Re-run focused tests**

Run: `./.venv/bin/python -m pytest backend/tests/test_conversation_authorization.py -q`

Expected: PASS

**Step 5: Run regression suite**

Run: `./.venv/bin/python -m pytest -q`

Expected: PASS with no new regressions.

---

### Task 2: Remove plaintext password persistence from setup/auth flow

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/auth.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `frontend/src/components/SetupWizard.jsx`
- Test: `backend/tests/test_auth_setup_hashing.py`

**Step 1: Write failing tests**

- Add tests that prove:
  - setup persistence does not write recoverable plaintext passwords into `.env`
  - auth reload accepts hashed user entries
  - legacy plaintext `AUTH_USERS` can still be migrated or rejected deterministically

**Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/tests/test_auth_setup_hashing.py -q`

Expected: FAIL because setup currently serializes plaintext `auth_users` into `.env`.

**Step 3: Minimal implementation**

- Choose one credential format and document it:
  - preferred: `AUTH_USERS` stores bcrypt hashes only, for example `{"alice":"$2b$..."}`.
- Hash passwords on the server before writing config.
- Make `backend/auth.py` treat stored values as hashes, not plaintext.
- Add a one-time compatibility path for legacy plaintext config if needed:
  - migrate to hashes at reload time and overwrite the legacy value
  - or reject startup with a precise error telling the operator to re-run setup
- Update Setup Wizard copy so generated passwords are presented as one-time credentials, not values the app will remember in readable form.

**Step 4: Re-run focused tests**

Run: `./.venv/bin/python -m pytest backend/tests/test_auth_setup_hashing.py -q`

Expected: PASS

**Step 5: Re-run auth + setup regressions**

Run: `./.venv/bin/python -m pytest backend/tests/test_runtime_settings_api.py backend/tests/test_execution_modes.py -q`

Expected: PASS

---

### Task 3: Replace mutable module-global config with typed settings and explicit reload boundaries

**Files:**
- Create: `backend/settings.py`
- Modify: `backend/config.py`
- Modify: `backend/database.py`
- Modify: `backend/auth.py`
- Modify: `backend/main.py`
- Modify: `backend/router_dispatch.py`
- Modify: `backend/openrouter.py`
- Modify: `backend/ollama.py`
- Test: `backend/tests/test_settings_reload.py`

**Step 1: Write failing tests**

- Add tests covering:
  - typed settings load from env
  - reload updates values consistently
  - database/config consumers do not retain stale env-derived globals

**Step 2: Run tests to verify they fail**

Run: `./.venv/bin/python -m pytest backend/tests/test_settings_reload.py -q`

Expected: FAIL because current config/database modules compute env-derived globals at import time.

**Step 3: Minimal implementation**

- Introduce a single typed settings object that owns env parsing.
- Keep a narrow `reload_settings()` surface if runtime setup must remain supported.
- Remove duplicate env parsing from `backend/database.py`.
- Stop spreading `config.*` mutable globals as implicit shared state where a function parameter or settings accessor is clearer.
- Preserve current public behavior; this is a plumbing cleanup, not a product change.

**Step 4: Re-run focused tests**

Run: `./.venv/bin/python -m pytest backend/tests/test_settings_reload.py -q`

Expected: PASS

**Step 5: Re-run backend suite**

Run: `./.venv/bin/python -m pytest -q`

Expected: PASS

---

### Task 4: Decompose backend API and streaming orchestration into smaller units

**Files:**
- Create: `backend/api/routes/conversations.py`
- Create: `backend/api/routes/setup.py`
- Create: `backend/api/routes/settings.py`
- Create: `backend/services/streaming_service.py`
- Create: `backend/services/conversation_service.py`
- Modify: `backend/main.py`
- Modify: `backend/council.py`
- Test: `backend/tests/test_streaming_disconnect.py`
- Test: `backend/tests/test_execution_modes.py`

**Step 1: Freeze current behavior with tests**

- Add or extend tests for:
  - streaming partial-save behavior on disconnect
  - title generation on first message
  - `chat_only`, `chat_ranking`, and `full` execution modes
  - stage heartbeat semantics

**Step 2: Run the targeted tests**

Run: `./.venv/bin/python -m pytest backend/tests/test_streaming_disconnect.py backend/tests/test_execution_modes.py -q`

Expected: PASS before refactor

**Step 3: Refactor in slices**

- Move route registration out of `backend/main.py` into smaller router modules.
- Extract the long `send_message_stream()` orchestration into a service that returns events or yields structured event objects.
- Keep SSE serialization close to the HTTP layer, not mixed with business orchestration.
- Reduce `backend/council.py` responsibility by moving tool-selection/search helpers or prompt-format helpers into dedicated modules if they are independently testable.

**Step 4: Re-run targeted tests after each extraction**

Run: `./.venv/bin/python -m pytest backend/tests/test_streaming_disconnect.py backend/tests/test_execution_modes.py -q`

Expected: PASS after every slice; do not batch all refactors into one giant change.

**Step 5: Re-run full backend suite**

Run: `./.venv/bin/python -m pytest -q`

Expected: PASS

---

### Task 5: Split oversized frontend components and replace ad hoc error UX

**Files:**
- Create: `frontend/src/hooks/useConversationStream.js`
- Create: `frontend/src/hooks/useModelCatalog.js`
- Create: `frontend/src/components/model-selector/`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/ChatInterface.jsx`
- Modify: `frontend/src/components/ModelSelector.jsx`
- Modify: `frontend/src/components/SetupWizard.jsx`
- Modify: `frontend/src/api.js`
- Test: `frontend/src/components/SetupWizard.test.jsx`
- Test: `frontend/src/components/ModelSelector.test.jsx`
- Test: `frontend/src/hooks/useConversationStream.test.jsx`
- Modify: `frontend/package.json`

**Step 1: Add a frontend test runner**

- Add `vitest` + React Testing Library.
- Add scripts:
  - `test`
  - `test:watch`

**Step 2: Write failing tests**

- Cover:
  - Setup Wizard validation and submit payload shaping
  - ModelSelector preset loading / router switching behavior
  - streaming event reducer/hook behavior
  - error rendering via toast UI instead of `alert()`

**Step 3: Refactor**

- Move streaming state management out of `App.jsx` into a hook.
- Split `ModelSelector.jsx` into focused sections:
  - presets
  - filters/sorting
  - selection grid
  - confirmation footer
- Replace `alert()` with the existing toast system for user-facing failures.
- Centralize API error normalization in `frontend/src/api.js`.
- Resolve current hook dependency warnings in `ModelSelector.jsx`.

**Step 4: Run frontend checks**

Run:
- `npm run lint`
- `npm run build`
- `npm run test -- --run`

Expected:
- lint: 0 errors, 0 warnings
- build: PASS
- tests: PASS

**Step 5: Keep behavior stable**

- Re-run a manual smoke check:
  - create conversation
  - send streaming message
  - abort stream
  - change title

---

### Task 6: Add repo-level quality gates, version hygiene, and missing documentation

**Files:**
- Modify: `pyproject.toml`
- Modify: `frontend/package.json`
- Modify: `VERSION`
- Modify: `README.md`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `.github/workflows/ci.yml`

**Step 1: Decide version source of truth**

- Use one source of truth for app versioning:
  - preferred: root `VERSION`
- Make backend and frontend build metadata derive from it, or explicitly document why they differ.

**Step 2: Add Python quality tooling**

- Add at least:
  - `ruff`
  - a formatter choice (`ruff format` or `black`)
  - optionally `mypy` if the team is willing to maintain it

**Step 3: Add CI**

- CI should run:
  - backend tests
  - frontend lint
  - frontend build
  - frontend tests once Task 5 lands

**Step 4: Fix docs drift**

- Update `README.md` so the documented version matches reality.
- Add the referenced `CONTRIBUTING.md` and `SECURITY.md`, or remove those sections if the project intentionally does not support them.
- Document Python version expectations explicitly; current local tests run on Python 3.10 while the Docker image uses Python 3.12.

**Step 5: Verify**

Run:
- `./.venv/bin/python -m pytest -q`
- `npm run lint`
- `npm run build`

Expected: PASS in local dev and in CI.

---

### Recommended Execution Order

1. Task 1
2. Task 2
3. Task 6 (quality gates early, but after the P0 fixes)
4. Task 3
5. Task 4
6. Task 5

### Exit Criteria

- Auth-enabled deployments enforce per-user conversation isolation.
- No plaintext user passwords are persisted by setup.
- Backend and frontend have stable automated checks in CI.
- Large monolithic files are reduced behind test-protected seams.
- Versioning and operator docs stop drifting.
