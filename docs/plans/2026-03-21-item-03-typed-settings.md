# Item 03: Typed Settings and Reload Boundaries

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace ad hoc mutable module-global configuration with a typed settings layer and explicit reload boundaries.

**Architecture:** Introduce a single settings owner that parses env state and exposes a narrow reload API. Consumers should stop computing env-derived globals independently and should rely on explicit settings access instead.

**Tech Stack:** Pydantic/BaseModel or equivalent typed config object, FastAPI, pytest.

---

## Design

### Problem

- `backend/config.py` mutates module globals in place.
- `backend/database.py` separately computes env-derived globals at import time.
- Reload behavior is difficult to reason about and easy to desynchronize.

### Design Decisions

- Keep runtime reload because setup wizard still depends on it.
- Avoid broad framework churn; add a small typed settings layer rather than overhauling the whole backend at once.
- Consolidate env parsing in one place.
- Define reload scope explicitly:
  - hot-reloadable: router choice, API keys, auth flags/users/secrets, optional search-provider toggles
  - restart-required: database backend selection and connection URLs, plus any setting that requires rebuilding long-lived engine/session state

### Files

- Create: `backend/settings.py`
- Modify: `backend/config.py`
- Modify: `backend/database.py`
- Modify: `backend/auth.py`
- Modify: `backend/router_dispatch.py`
- Modify: `backend/openrouter.py`
- Modify: `backend/ollama.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_settings_reload.py`

### Risks

- Import order bugs may surface during migration.
- Setup wizard updates must still refresh the right in-memory state.
- Existing tests may monkeypatch old module-level names.
- Database engine/session lifecycle can remain stale if restart-required boundaries are not enforced clearly.

### Local E2E Gate

1. Start app locally.
2. Change router/auth-related settings through setup/runtime flows.
3. Verify models/auth/setup status endpoints reflect new values without inconsistent stale state.

## Implementation

### Task 1: Add failing reload/config tests

**Files:**
- Create: `backend/tests/test_settings_reload.py`

**Step 1: Write the failing test**

- Verify typed settings load expected defaults.
- Verify reload updates consumers consistently.
- Verify database/settings state does not drift after reload.
- Verify restart-required settings are classified separately from hot-reloadable settings.

**Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_settings_reload.py -q`

Expected: FAIL

### Task 2: Introduce the typed settings owner

**Files:**
- Create: `backend/settings.py`
- Modify: `backend/config.py`
- Modify: `backend/database.py`

**Step 1: Minimal implementation**

- Add a typed settings object with env parsing.
- Route existing config access through that object.
- Remove duplicate env parsing from `backend/database.py`.
- Expose restart-required vs hot-reloadable classification clearly enough for setup flow to report it.

**Step 2: Re-run focused test**

Run: `./.venv/bin/python -m pytest backend/tests/test_settings_reload.py -q`

Expected: partially passing or still failing until consumer migration is complete.

### Task 3: Migrate critical consumers

**Files:**
- Modify: `backend/auth.py`
- Modify: `backend/openrouter.py`
- Modify: `backend/ollama.py`
- Modify: `backend/router_dispatch.py`
- Modify: `backend/main.py`

**Step 1: Minimal implementation**

- Move high-value consumers to explicit settings access.
- Keep compatibility shims only where necessary.

**Step 2: Re-run focused test**

Run: `./.venv/bin/python -m pytest backend/tests/test_settings_reload.py -q`

Expected: PASS

### Task 4: Verification, review, commit

**Step 1: Run broader backend checks**

Run: `./.venv/bin/python -m pytest -q`

Expected: PASS

**Step 2: Run local E2E gate**

- setup/runtime setting change
- models endpoint
- auth status
- confirm restart-required settings are surfaced as such rather than silently “reloaded”
- one conversation send flow

**Step 3: External agent review**

- Ask the second coding agent to review stale-config risks, import-order issues, and reload semantics.

**Step 4: Commit**

```bash
git add backend/settings.py backend/config.py backend/database.py backend/auth.py backend/router_dispatch.py backend/openrouter.py backend/ollama.py backend/main.py backend/tests/test_settings_reload.py
git commit -m "refactor: centralize typed settings and reload behavior"
```
