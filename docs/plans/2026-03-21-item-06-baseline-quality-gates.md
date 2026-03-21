# Item 06: Baseline Quality Gates and CI

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Establish the minimum automated guardrails before the largest refactors begin.

**Architecture:** Add only the smallest enforceable baseline now: backend tests, frontend lint/build, and frontend tests once Item 05 lands. This item exists early in the sequence specifically to reduce regression risk for Items 03-05.

**Tech Stack:** pytest, ESLint, Vite build, GitHub Actions, lightweight Python lint/format tooling.

---

## Design

### Problem

- The repo currently relies on ad hoc local validation.
- Python has no visible in-repo lint/format gate.
- Invasive refactors are planned immediately after this stage.

### Design Decisions

- Prefer a small mandatory baseline over a large aspirational CI suite.
- Only add checks that are runnable locally by the implementation agent.
- Documentation/version cleanup is intentionally deferred to Item 07.

### Files

- Modify: `pyproject.toml`
- Create: `.github/workflows/ci.yml`

### Local E2E Gate

1. Run the same local command matrix that CI will run.
2. Start Docker Compose and run the preflight E2E harness from the master plan.

## Implementation

### Task 1: Add minimal Python quality tooling

**Files:**
- Modify: `pyproject.toml`

**Step 1: Minimal implementation**

- Add lightweight Python lint/format tooling.
- Keep command count small and enforceable.

**Step 2: Verify locally**

Run the chosen Python checks locally.

Expected: PASS

### Task 2: Add baseline CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Step 1: Minimal implementation**

- Run:
  - backend tests
  - frontend lint
  - frontend build
  - frontend tests conditionally or after Item 05

**Step 2: Verify locally**

Run:
- `./.venv/bin/python -m pytest -q`
- `npm run lint`
- `npm run build`

Expected: PASS

### Task 3: Review, verify, commit

**Step 1: External agent review**

- Ask the second coding agent to review CI completeness, local reproducibility, and unnecessary tool churn.

**Step 2: Run local E2E gate**

- preflight API checks
- baseline browser smoke

**Step 3: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml
git commit -m "chore: add baseline quality gates"
```
