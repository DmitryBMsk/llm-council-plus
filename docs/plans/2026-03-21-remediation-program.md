# Remediation Program Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Execute the codebase remediation safely: one plan item at a time, one commit per item, mandatory independent coding-agent review, and mandatory local E2E validation before moving to the next item.

**Architecture:** Treat the review findings as a bounded remediation program rather than a broad refactor. The sequence is deliberately front-loaded with security and isolation fixes, then moves to configuration correctness, backend decomposition, frontend decomposition, and finally repository hygiene and quality gates.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy/JSON storage, React + Vite + Zustand, pytest, ESLint, Docker Compose, local Playwright MCP for E2E smoke.

---

## Process Contract

These rules apply to every remediation item:

1. One active item at a time.
2. One remediation item equals one implementation commit.
3. Before any implementation, the item’s design section is considered the source of truth.
4. Every item starts with failing tests where practical.
5. Every item must pass focused tests before broader verification.
6. Every item must receive review from another coding agent before commit.
7. Every item must pass local E2E validation before commit.
8. Do not start the next item until the current item is reviewed, verified, and committed.

## Repo Safety Gates

These safety gates are mandatory for every item:

1. Before editing any target symbol or file area, run GitNexus impact analysis on the planned change surface.
2. Before commit, run GitNexus change detection on the current diff to inspect affected flows and unexpected blast radius.
3. Record GitNexus outputs and the external coding-agent review in:
   - `docs/plans/2026-03-21-remediation-review-log.md`

Recommended tooling:

- Pre-edit: `mcp__gitnexus__impact`
- Pre-commit: `mcp__gitnexus__detect_changes`

## Commit Contract

For each item:

1. Read the relevant item plan.
2. Write or extend failing tests.
3. Implement the minimal change set.
4. Run focused test commands.
5. Run the item’s local E2E gate.
6. Send the diff to another coding agent for review.
7. Address findings.
8. Re-run tests and E2E.
9. Commit exactly that item.

## Review Contract

For each item, the external coding-agent review must answer:

- Does the diff fully implement the item design?
- Did the change introduce a security, ownership, or regression risk?
- Are tests sufficient for the changed behavior?
- Is the commit scope still limited to the active item?
- Were GitNexus safety checks run and recorded?

## Review Log

- Use: `docs/plans/2026-03-21-remediation-review-log.md`
- Record one row per implemented item.
- Minimum fields:
  - item
  - commit
  - reviewer agent
  - review focus
  - findings summary
  - GitNexus impact summary
  - GitNexus detect_changes summary
  - final verification result

## Local E2E Baseline

Unless the item specifies a more focused E2E flow, use this baseline:

1. `docker compose up -d --build`
2. `curl -fsS http://localhost:8001/api/version`
3. `curl -fsS http://localhost:8001/api/auth/status`
4. `curl -fsSI http://localhost/ | sed -n '1,10p'`
5. Open `http://localhost/`
6. Create a conversation
7. Send the fixed smoke prompt: `Local remediation smoke test`
8. Verify Stage 1 starts
9. Verify final response or expected partial flow
10. Send a second prompt and verify Stop/abort still works

For auth-related items, add login/setup-specific checks from the item document.

## Preflight E2E Harness

Treat this as the repeatable minimum smoke flow for every item:

### API preflight

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://localhost:8001/api/version
curl -fsS http://localhost:8001/api/auth/status
curl -fsSI http://localhost/ | sed -n '1,10p'
```

Expected:

- backend container healthy
- frontend serving `200 OK`
- backend version endpoint responds
- auth status endpoint responds

### UI smoke

1. Open `http://localhost/`
2. If Setup Wizard appears unexpectedly for a non-setup item, stop and investigate
3. Create a new conversation
4. Use the default council creation flow
5. Send `Local remediation smoke test`
6. Observe streaming start
7. Send a second prompt and click `Stop`
8. Verify the UI remains usable after cancellation

## Execution Sequence

1. [Item 01: Conversation Ownership Enforcement](./2026-03-21-item-01-conversation-ownership.md)
2. [Item 02: Auth Credential Storage Hardening](./2026-03-21-item-02-auth-credential-storage.md)
3. [Item 06: Baseline Quality Gates and CI](./2026-03-21-item-06-baseline-quality-gates.md)
4. [Item 03: Typed Settings and Reload Boundaries](./2026-03-21-item-03-typed-settings.md)
5. [Item 04: Backend API and Streaming Decomposition](./2026-03-21-item-04-backend-decomposition.md)
6. [Item 05: Frontend State, Errors, and Component Decomposition](./2026-03-21-item-05-frontend-decomposition.md)
7. [Item 07: Version and Documentation Hygiene](./2026-03-21-item-07-version-and-documentation-hygiene.md)

## Why This Order

- Item 01 and Item 02 close the most serious user-facing risks first.
- Item 06 establishes baseline automation before the largest refactors begin.
- Item 03 reduces hidden configuration regressions before structural refactors.
- Item 04 and Item 05 break down the highest-complexity modules only after behavior is better protected and checks exist.
- Item 07 cleans up version/documentation drift once the execution baseline is stable.

## Item Exit Criteria

An item is complete only when all of the following are true:

- Implementation matches the item design.
- Focused tests pass.
- Broader regression commands pass.
- External coding-agent review is complete and findings are addressed.
- Local E2E gate passes.
- The item is committed separately.

## Program Exit Criteria

- Auth-enabled deployments enforce per-user conversation isolation.
- No plaintext user passwords are persisted by setup.
- Config reload behavior is explicit and testable.
- Backend streaming/API logic is no longer concentrated in a single giant route module.
- Frontend stateful flows are smaller, tested, and do not rely on `alert()`.
- CI enforces backend tests, frontend lint/build/tests, and version/documentation drift is reduced.
