# Item 05: Frontend State, Errors, and Component Decomposition

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce frontend change risk by adding a real test harness, centralizing error handling, and splitting the largest stateful components into smaller units.

**Architecture:** Move cross-cutting stateful logic into hooks and small view components. Replace browser alerts with the existing toast system so failures are visible, testable, and consistent.

**Tech Stack:** React, Vite, Zustand, ESLint, Vitest, React Testing Library.

---

## Design

### Problem

- `App.jsx` and `ModelSelector.jsx` are too large.
- Core flows still use `alert()` and scattered `console.*`.
- There is no visible frontend automated test harness.

### Design Decisions

- Add frontend tests before the bigger component split.
- Extract hooks for streaming and model-catalog state.
- Keep visual behavior stable; do not redesign the UI as part of this item.
- Include parser/session/storage-heavy surfaces in tests, not only visible component rendering.

### Files

- Create: `frontend/src/hooks/useConversationStream.js`
- Create: `frontend/src/hooks/useModelCatalog.js`
- Create: `frontend/src/components/model-selector/`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/ChatInterface.jsx`
- Modify: `frontend/src/components/ModelSelector.jsx`
- Modify: `frontend/src/components/SetupWizard.jsx`
- Modify: `frontend/src/api.js`
- Modify: `frontend/package.json`
- Test: `frontend/src/components/SetupWizard.test.jsx`
- Test: `frontend/src/components/ModelSelector.test.jsx`
- Test: `frontend/src/hooks/useConversationStream.test.jsx`

### Risks

- Hook extraction can break stale closure behavior.
- ModelSelector presets/router switching have hidden edge cases.
- Error UX changes can regress existing flows if not tested.
- `api.js` SSE parsing, session-expiry logout, attachment uploads, and localStorage-backed selector state are likely regression hotspots.

### Local E2E Gate

1. Start app locally.
2. Open setup or main chat UI.
3. Create conversation through Model Selector.
4. Send streaming message.
5. Trigger a recoverable failure path and verify toast-based feedback.
6. Verify abort/stop still works.

## Implementation

### Task 1: Add frontend test harness

**Files:**
- Modify: `frontend/package.json`
- Create: frontend test setup files as needed

**Step 1: Minimal implementation**

- Add `vitest` and React Testing Library.
- Add `test` and `test:watch` scripts.

**Step 2: Write initial failing tests**

- Setup Wizard validation/submission
- streaming hook behavior
- ModelSelector preset load/router switch behavior
- `api.js` SSE event parsing
- auth/session-expiry behavior
- attachment/upload error flow
- localStorage-backed last-selection restore

**Step 3: Run tests to verify they fail**

Run: `npm run test -- --run`

Expected: FAIL

### Task 2: Centralize error handling and remove `alert()`

**Files:**
- Modify: `frontend/src/api.js`
- Modify: `frontend/src/components/ChatInterface.jsx`
- Modify: `frontend/src/components/SetupWizard.jsx`
- Modify: `frontend/src/App.jsx`

**Step 1: Minimal implementation**

- Normalize API errors in one place.
- Replace `alert()` calls with the toast mechanism already used by the app.
- Preserve session-expiry behavior and make it testable.

**Step 2: Re-run targeted tests**

Run: `npm run test -- --run`

Expected: more tests pass, error paths are covered.

### Task 3: Split large stateful components

**Files:**
- Create: `frontend/src/hooks/useConversationStream.js`
- Create: `frontend/src/hooks/useModelCatalog.js`
- Create: `frontend/src/components/model-selector/`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/ModelSelector.jsx`

**Step 1: Minimal implementation**

- Move streaming state/event handling out of `App.jsx`.
- Break `ModelSelector.jsx` into smaller composable pieces.
- Resolve the current hook dependency warnings.

**Step 2: Re-run frontend checks**

Run:
- `npm run lint`
- `npm run build`
- `npm run test -- --run`

Expected:
- lint: 0 errors, 0 warnings
- build: PASS
- tests: PASS

### Task 4: Verification, review, commit

**Step 1: Run local E2E gate**

- configure/create conversation
- send/abort stream
- observe toasts on failure path
- attachment upload flow
- returning-user localStorage state in ModelSelector

**Step 2: External agent review**

- Ask the second coding agent to review hook boundaries, stale state risks, and missing frontend tests.

**Step 3: Commit**

```bash
git add frontend/package.json frontend/src/App.jsx frontend/src/api.js frontend/src/components/ChatInterface.jsx frontend/src/components/ModelSelector.jsx frontend/src/components/SetupWizard.jsx frontend/src/hooks frontend/src/components/model-selector frontend/src/components/SetupWizard.test.jsx frontend/src/components/ModelSelector.test.jsx frontend/src/hooks/useConversationStream.test.jsx
git commit -m "refactor: decompose frontend stateful flows"
```
