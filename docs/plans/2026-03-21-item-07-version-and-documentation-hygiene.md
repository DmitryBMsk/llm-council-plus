# Item 07: Version and Documentation Hygiene

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate version drift and make the public documentation match the actual repository and local setup flow.

**Architecture:** After the codebase behavior and quality gates are in better shape, align metadata and operator documentation around one coherent version story and one truthful local workflow.

**Tech Stack:** Markdown docs, package metadata, repo config files.

---

## Design

### Problem

- Version numbers differ across README, Python metadata, and frontend metadata.
- Repo docs and maintenance expectations can drift from reality.

### Design Decisions

- Choose one version source of truth, preferably root `VERSION`.
- Keep README aligned with actual local startup flow and existing files.
- Add only the docs that are justified by the repo’s intended maintenance posture.

### Files

- Modify: `README.md`
- Modify: `VERSION`
- Modify: `pyproject.toml`
- Modify: `frontend/package.json`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`

### Local E2E Gate

1. Follow README quick-start literally on local stack.
2. Verify version endpoints and docs agree.

## Implementation

### Task 1: Align version source of truth

**Files:**
- Modify: `VERSION`
- Modify: `pyproject.toml`
- Modify: `frontend/package.json`
- Modify: `README.md`

**Step 1: Minimal implementation**

- Decide the source of truth.
- Align metadata and README language with that source.

**Step 2: Verify**

Run:
- `cat VERSION`
- inspect backend/frontend metadata

Expected: consistent version story.

### Task 2: Fix documentation drift

**Files:**
- Modify: `README.md`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`

**Step 1: Minimal implementation**

- Ensure README only references files that exist.
- Ensure the setup/run steps match the current local workflow.
- Document contribution/security expectations honestly.

### Task 3: Review, verify, commit

**Step 1: External agent review**

- Ask the second coding agent to review doc truthfulness, version consistency, and maintenance posture.

**Step 2: Run local E2E gate**

- `docker compose up -d --build`
- follow README quick-start
- verify the documented flow works

**Step 3: Commit**

```bash
git add README.md VERSION pyproject.toml frontend/package.json CONTRIBUTING.md SECURITY.md
git commit -m "docs: align versioning and repository docs"
```
