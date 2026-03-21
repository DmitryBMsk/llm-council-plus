# Item 02: Auth Credential Storage Hardening

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop persisting recoverable plaintext passwords in setup/auth configuration while keeping the login flow usable.

**Architecture:** The setup endpoint should hash passwords before writing configuration. The auth module should consume stored hashes directly. Any temporary compatibility path for legacy plaintext should be explicit and short-lived.

**Tech Stack:** FastAPI, bcrypt, pytest, React setup wizard.

---

## Design

### Problem

- Setup currently writes plaintext credentials into `.env` as `AUTH_USERS`.
- Password hashing happens only after secrets are already persisted.
- This breaks a basic credential-storage expectation.

### Design Decisions

- Store bcrypt hashes only in persisted config.
- Keep `AUTH_USERS` as JSON for minimal migration cost, but change values to hashes.
- If legacy plaintext is detected, either migrate once or reject startup with a clear operator message.
- Persisted format is explicit:
  - `AUTH_USERS` stores JSON object values as bcrypt hashes, for example `{"alice":"$2b$12$..."}`.
- Hash persistence must be validated through a Docker/Compose round-trip because bcrypt hashes contain `$` characters.

### Files

- Modify: `backend/main.py`
- Modify: `backend/auth.py`
- Modify: `frontend/src/components/SetupWizard.jsx`
- Modify: `.env.example`
- Modify: `README.md`
- Test: `backend/tests/test_auth_setup_hashing.py`

### Risks

- Existing setups may already rely on plaintext `AUTH_USERS`.
- Wizard copy must avoid implying that generated passwords are stored recoverably.
- Reload logic must still work after setup changes.
- `.env` quoting/escaping must preserve bcrypt hashes exactly through file write, `load_dotenv`, Compose env injection, and container startup.

### Local E2E Gate

1. Run setup flow locally with auth enabled.
2. Create one user through the wizard.
3. Verify `.env` does not contain that user’s plaintext password.
4. Restart via Docker Compose and verify the stored hash survives round-trip loading.
5. Login with the generated password.
6. Verify auth status and protected routes still work.

## Implementation

### Task 1: Add failing tests for persisted credential format

**Files:**
- Create: `backend/tests/test_auth_setup_hashing.py`

**Step 1: Write the failing test**

- Verify setup persistence writes hashes, not plaintext.
- Verify auth reload accepts hashed stored values.
- Verify legacy plaintext handling is deterministic.

**Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_auth_setup_hashing.py -q`

Expected: FAIL

### Task 2: Change setup persistence to hash before write

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/auth.py`

**Step 1: Minimal implementation**

- Add helper to hash incoming passwords before they enter `updates["AUTH_USERS"]`.
- Change auth loading to treat stored values as hashes.
- Add compatibility handling for legacy plaintext.
- Ensure `.env` serialization preserves bcrypt hashes verbatim.

**Step 2: Re-run focused test**

Run: `./.venv/bin/python -m pytest backend/tests/test_auth_setup_hashing.py -q`

Expected: PASS

### Task 3: Update UX and docs

**Files:**
- Modify: `frontend/src/components/SetupWizard.jsx`
- Modify: `.env.example`
- Modify: `README.md`

**Step 1: Minimal implementation**

- Update setup copy to explain that generated passwords are one-time operator-facing values.
- Document the persisted hash-only format.

**Step 2: Re-run focused regressions**

Run: `./.venv/bin/python -m pytest backend/tests/test_runtime_settings_api.py -q`

Expected: PASS

### Task 4: Full verification, review, commit

**Step 1: Run broader checks**

Run:
- `./.venv/bin/python -m pytest -q`
- `npm run lint`

Expected: PASS

**Step 2: Run local E2E gate**

- Complete setup wizard locally
- inspect persisted `AUTH_USERS` in `.env`
- restart with Docker Compose
- Login as configured user
- Access a protected conversation flow

**Step 3: External agent review**

- Request a second coding agent to review auth storage, migration behavior, and secret-handling assumptions.

**Step 4: Commit**

```bash
git add backend/main.py backend/auth.py frontend/src/components/SetupWizard.jsx .env.example README.md backend/tests/test_auth_setup_hashing.py
git commit -m "fix: store only hashed auth credentials"
```
