# LLM Council Plus — Prioritized Action Plan

Source: 41 adversarially-verified findings, deduped to ~27 actionable items. Priorities use the
skeptic's `verified_severity`, NOT the original `severity` (they disagree often). All paths are
absolute under `/Users/dmitrybakhtin/PythonHome/llm-council-plus`.

Legend: **P0** correctness/security do-first · **P1** high value · **P2** nice-to-have. Effort S/M/L.

---

## Quick wins (this week) — all S effort, high leverage

> **✅ DONE 2026-06-19** — all 6 implemented on branch `quick-wins-review-2026-06`.
> Verified: backend 109 tests pass on Python 3.12 (ruff clean); frontend lint clean, build OK,
> 12 tests pass. New backend test: `backend/tests/test_stage3_empty_guard.py` (covers #6).

| # | What | File | Why |
|---|------|------|-----|
| 1 | Merge metadata on `stage2_complete` (`{ ...currentMetadata, ...event.metadata }`) instead of wholesale replace | `frontend/src/App.jsx:465` | One-line fix stops search-context results from vanishing mid-interaction |
| 2 | Reject non-`http(s)` URL schemes before rendering `<a href={r.url}>` | `frontend/src/components/SearchContext.jsx:139-146` | Closes a `javascript:`/`data:` XSS vector from poisoned search results |
| 3 | Add `.catch()` to `api.getVersion()` / `api.getUsers()` in Sidebar effect | `frontend/src/components/Sidebar.jsx:54-61` | Removes unhandled promise rejections on network/parse failure |
| 4 | Align Python version (Dockerfile `3.12` vs `.python-version`/CI `3.10`) | `backend/Dockerfile:1`, `.python-version`, `.github/workflows/ci.yml:18` | Prod runs an untested interpreter; pick one target |
| 5 | Replace hand-written `uv pip install <list>` with `uv sync` in CI | `.github/workflows/ci.yml:24-29` | CI tests ~12 fewer deps than prod; closes drift in one line |
| 6 | Guard Stage 3 against empty `stage1_data` (return user-facing error, don't query chairman) | `backend/council.py:968-1034` | Prevents a fully hallucinated "final answer" when all Stage 1 models fail |

Overflow S-effort candidates (do if time permits): JWT expiry (B1.5), ranking-parse logging (part of A1.1).

---

## (A) FUNCTIONALITY / PRODUCT improvements

### P0 — correctness, user-visible breakage

**A0.1 — Stage 2 metadata clobber loses `tool_outputs`** · S · new
WHAT: change `metadata: event.metadata` to a merge (`{ ...currentMetadata, ...event.metadata }`).
WHY: **verified** — `ChatInterface.jsx:341` renders `<SearchContext toolOutputs={msg.metadata?.tool_outputs || msg.tool_outputs} />`,
so the primary read is `msg.metadata.tool_outputs`. The wholesale replace at `App.jsx:465` overwrites it
with the Stage 2 event's metadata (no `tool_outputs`), so the search-context panel empties after Stage 2.
(There is a `|| msg.tool_outputs` top-level fallback, but the streaming path stores tool outputs under
`metadata`, not top-level, so the fallback does not save it.) File: `frontend/src/App.jsx:465`. (Also
Quick Win #1.) Merge is safe regardless of whether the Stage 2 event re-sends `tool_outputs`.

**A0.2 — Stage 3 hallucinates when all Stage 1 models fail** · S · new
WHAT: after the `stage1_data = [... if result.get('response')]` filter (council.py:970), add
`if not stage1_data:` → log + return a clear error ("all council models failed, please retry")
instead of building TOON from `[]` and querying the chairman.
WHY: the existing `if not stage1_results:` guard (council.py:957, **verified present** — returns a
clean `error: True` dict) only catches a fully empty list. When models fail they remain in
`stage1_results` as error entries *without* a `response` key, so the guard passes; the response-filter
at line 970 then reduces `stage1_data` to `[]`, and the chairman is asked to synthesize from nothing.
The post-filter `stage1_data`, not `stage1_results`, is the correct emptiness check.
File: `backend/council.py:957,968-1034`. Caller: `backend/api/routes/conversations.py:611-620`.

### P1 — high value

**A1.1 — Ranking parser: silent drops + format brittleness + no UI visibility** · M · new
(merges `parsing-empty-ranking` + `ranking-parser-misformat-silent`)
WHAT: (a) log at the Stage 2 call site when a non-empty model response yields an empty parsed ranking;
(b) broaden the `Response [A-Z]` regex to tolerate `**Response A**`, lowercase, abbreviations;
(c) surface an "unparseable ranking" badge in the UI. WHY: malformed Stage 2 output silently drops a
model from voting with zero operator/user signal; position is also derived from text order, not the
model's stated numbers. Files: `backend/council.py:1094-1125` (parser), `:908` (call site for
logging — not inside the parser, which is called twice), `:1147-1162` (aggregate),
`frontend/src/components/Stage2.jsx:103-117`.

**A1.2 — No in-UI retry / regenerate / skip-to-Stage-3 actions** · L · new
WHAT: add "Retry model" on failed Stage 1 tabs, a message-level "Regenerate", and "Skip to Stage 3";
requires backend partial-rerun endpoints. WHY: a single failed model forces re-sending the whole
query. Files: `frontend/src/components/Stage1.jsx:73-81`, `frontend/src/App.jsx:633-641`,
`backend/api/routes/conversations.py` (new endpoints), `frontend/src/api.js`.

**A1.3 — Drive auto-upload only fires in full mode** · S→M · new
WHAT: trigger upload after the terminal stage of every execution mode (and render the manual upload
button when `stage3` is absent). WHY: `chat_only`/`chat_ranking` users get neither auto nor manual
upload despite stored responses. Files: `frontend/src/App.jsx:521-533`,
`frontend/src/components/ChatInterface.jsx:395-452`, backend `complete`-event branches in
`backend/api/routes/conversations.py:535,602`.

### P2 — nice-to-have

**A2.1 — Mobile/tablet responsiveness absent** · M · new
WHAT: add `@media (max-width: 768px)` rules (collapsible sidebar, vertical stack, scrollable tabs).
WHY: fixed-width sidebar breaks layout < 768px. Files: `frontend/src/App.css`,
`frontend/src/components/Sidebar.css`, `frontend/src/components/ChatInterface.css`.

**A2.2 — Token cost / real spend visibility** · M · new
WHAT: capture per-model usage from OpenRouter responses (currently discarded at
`backend/openrouter.py:132-135`), surface estimated cost + token spend in TokenStats. WHY: users only
see TOON compression %, not whether a query cost $0.01 or $1.00. File:
`frontend/src/components/TokenStats.jsx:12-51`.

---

## (B) CODEBASE / ENGINEERING improvements

### P0 — security + data integrity

**B0.1 — Setup endpoint open indefinitely in Ollama mode** · M · new — **highest-priority security item** — ✅ DONE 2026-06-19 (branch `p0-security-correctness`): durable `data/.setup_complete` marker gates the endpoint regardless of router type / .env presence. **Residual (accepted, user chose marker over SETUP_TOKEN):** the *first-run window* is still unauthenticated — on a fresh deploy an attacker who races the operator can run setup first and lock them out. Rate-limiting or `SETUP_TOKEN` remains the defense for that window (tracked, not done). NOTE: T4 still blocked — setup still writes secrets to `.env`; only the gate moved off `.env`.
WHAT: gate `/api/setup/config` independent of router type — disable after first run via an
env-backed flag (not just the `.env` file check, which fails when compose uses `environment:` vars)
and/or require a `SETUP_TOKEN`; add rate limiting. WHY: in Ollama deployments the line-93 gate
(`ROUTER_TYPE=="openrouter" and OPENROUTER_API_KEY`) is always false, and the `.env` SETUP_COMPLETE
fallback (lines 100-111) silently `pass`es when no `.env` file exists — an unauthenticated attacker
can inject `AUTH_USERS`, `JWT_SECRET`, or swap the router. File: `backend/api/routes/setup.py:80-111`.
Relates to KNOWN-DEFERRED T4 (the writable `.env` is the root enabler; see Tracked/deferred).

**B0.2 — SearchContext renders unsanitized `href` (XSS)** · S · new
See Quick Win #2. File: `frontend/src/components/SearchContext.jsx:139-146`. Validate with
`new URL()` in try/catch or a scheme allowlist. Gated: requires a poisoned/compromised search API,
but the sink is real and React 19 does not block `javascript:`.

**B0.3 — PDF/text uploads not size-checked before parsing (DoS)** · M · new — 🟡 PARTIAL 2026-06-19: added 20MB pre-parse cap for all file types in `/api/upload` (reduces large-file memory pressure). **Still OPEN (P1):** a PDF *decompression bomb* is small on disk and huge in memory, so it slips under the byte cap and still detonates in `pymupdf4llm.to_markdown`. Real fix = parse timeout + memory/RSS bound (needs a killable subprocess, not `signal.alarm` on a worker thread).
WHAT: enforce a pre-parse byte limit (~20 MB) for PDF/text before `parse_file()`, and add a
pymupdf render timeout. WHY: the size check at `:272` runs only for images; a <25 MB PDF bomb expands
in pymupdf before the 50k-char truncation at `:296` ever applies. Nginx `client_max_body_size 25m`
only protects the proxied path, not direct backend access inside the Docker network. Files:
`backend/api/routes/conversations.py:266-279,296-300`, `backend/file_parser.py:33-40`.

**B0.4 — Race condition in DB storage read-modify-write** · M · new — **DB-mode only (JSON is default)** — ⚠️ DEFERRED 2026-06-19 (user: JSON is prod, DB unused): documented the non-atomic RMW at all 3 sites in `storage.py`; full atomic-txn fix deferred until SQL backend is a prod target.
(merges `race-db-storage-add-user` + `-add-assistant` + `-title-update` — one root cause)
WHAT: add an atomic `_db_update_conversation()` mirroring the JSON `_json_update_conversation()`
file-lock pattern (single transaction or `SELECT ... FOR UPDATE`). WHY: `add_user_message`,
`add_assistant_message`, `update_conversation_title` each do `get_conversation()` then
`save_conversation()` across two separate sessions → lost updates under concurrency. The JSON path is
already safe; only `DATABASE_TYPE=postgresql/mysql` is affected, so impact is gated on whether DB mode
is actually deployed (see Open Questions). Files: `backend/storage.py:557-568,611-618,642-645`.

### P1 — high value

**B1.1 — Add propTypes to the 4 uncovered components** · M · new
WHAT: ChatInterface, ModelSelector, LoginScreen, SetupWizard. WHY: completes the partial coverage
PR#22 started (it merged Sidebar propTypes). Files:
`frontend/src/components/{ChatInterface,ModelSelector,LoginScreen,SetupWizard}.jsx`.

**B1.2 — Add code-coverage measurement** · S · new
WHAT: `pytest-cov` + `pytest --cov=backend` in CI; `@vitest/coverage-v8` + coverage config in
`frontend/vitest.config.js`. WHY: tests run but coverage is invisible; needed as the baseline for the
Bigger Bets test work. Files: `pyproject.toml:61-65`, `.github/workflows/ci.yml`,
`frontend/vitest.config.js`, `frontend/package.json`.

**B1.3 — Migrate FastAPI `on_event("startup")` → lifespan** · S · new
(merges `fastapi-on-event-deprecated` + `ops-fastapi-deprecated-event` — same line)
File: `backend/main.py:32`. WHY: deprecated; future FastAPI removal risk. (Note: unrelated to the
"coroutine never awaited" test warnings — those are MagicMock auto-spec artifacts.)

**B1.4 — DB connection pool sizing** · S · new
WHAT: set explicit `pool_size`/`max_overflow` and add `pool_recycle=3600` to PostgreSQL. WHY: single
async worker can exhaust the default 15-connection ceiling under load; Postgres lacks recycle.
File: `backend/database.py:63-74`. DB-mode only.

**B1.5 — JWT expiry 60d → 7d (+ refresh-token decision)** · S · new
File: `backend/auth.py:24`. WHY: 60-day stolen-token window. Gated: self-hosted/optional-auth tool,
so confirm intent (Open Questions) before tightening.

### P2 — hardening / hygiene

**B2.1 — DB URL: raise on missing config instead of hardcoded localhost fallback** · S · new
File: `backend/database.py:35-38`.

**B2.2 — CORS: replace wildcard methods/headers with explicit lists** · S · new
File: `backend/main.py:41-47`. Defense-in-depth (origins already localhost-only).

**B2.3 — Untrusted web/tool output marking** · M · new (verified LOW)
WHAT: wrap search/tool outputs in explicit `[UNTRUSTED EXTERNAL SOURCE]` delimiters before embedding
in prompts. Files: `backend/council.py:584,994-996`. (Note: original finding's line 488-489 cite is
wrong; real sinks are 584 and 994-996.)

**B2.4 — Attachment delimiter-injection hardening** · M · new (verified LOW — self-injection only)
File: `backend/api/routes/conversations.py:137`. Defense-in-depth, not a security boundary.

**B2.5 — JSON storage exposes corrupted files** · M · new (LOW)
WHAT: track/expose malformed conversation files (diagnostics endpoint or response warning). File:
`backend/storage.py:245-247`.

**B2.6 — Structured logging w/ request/conversation correlation** · M · new (LOW)
WHAT: `contextvars` for request_id/conversation_id in log format. Files: `backend/main.py:10-12`,
`backend/council.py`.

**B2.7 — Performance metrics** · M · new (LOW)
WHAT: persist/emit stage durations (computed but discarded today). Files: `backend/council.py`,
`backend/api/routes/conversations.py`.

**B2.8 — Explain ModelSelector eslint-disable comments** · S · new (LOW)
WHAT: add justification text or `useCallback`-wrap `loadModels`/`loadLastUsedSelection`. File:
`frontend/src/components/ModelSelector.jsx:129,137`.

**B2.9 — LangChain version upper bounds** · S · new (LOW — optional dep, graceful fallback)
File: `pyproject.toml:39-40`. Confirm against locked versions before pinning (current lock is 1.x;
a naive `<0.3` would break it).

**B2.10 — Docker optional-extras decision** · S · new (LOW)
WHAT: decide + document whether finance/embeddings extras ship in Docker (`--no-emit-project` omits
them today). File: `backend/Dockerfile:26-33`. Graceful degradation already in place.

**B2.11 — Frontend healthcheck verifies API proxy** · S · new (LOW)
WHAT: `wget .../api/version` so nginx isn't "healthy" while the backend proxy is broken. File:
`frontend/Dockerfile:46`.

### Tracked / deferred (report-only, do not re-open as new)
- **`.env` writable mount** — KNOWN-DEFERRED T4; blocked because setup.py writes secrets to `.env`.
  Resolving B0.1 (move setup state out of `.env`) is the unblocker. Files: `docker-compose.yml:38`,
  `backend/api/routes/setup.py:194`.
- **Optional deps hollow in CI** — tracked debt; covered by the `uv sync` fix (Quick Win #5) plus a
  decision on integration coverage (Bigger Bets, Phase 1.4).

---

## Bigger bets (sequenced — test-first, decomposition second)

**Hard rule: build the characterization net BEFORE splitting any large file.** You cannot safely
decompose a 1292-line module without tests pinning current behavior.

**Phase 1 — Test net (do first)**
1. Add coverage tooling (B1.2) — establishes the baseline.
2. Frontend component tests: SetupWizard (form validation/submit), ModelSelector (preset load/filter),
   ChatInterface (streaming render). Files: `frontend/src/components/*.test.jsx`. Effort L.
   (merges `frontend-component-tests-missing` + Task 5 backlog)
3. App.jsx streaming characterization tests: `updateStreamingState` immutable merge, conversation
   switch mid-stream, abort clears state, and a regression test for A0.1 (stage2_complete preserves
   tool_outputs). File: `frontend/src/App.jsx`. Effort L.
4. One backend integration test running real `council.py` + `conversations.py` with only OpenRouter
   and storage mocked, to cover the `send_message_stream` ↔ stage-function seam (untested today).
   Effort M. (`backend-tests-over-mocking` — note: per-stage integration already partly exists in
   `test_council_router_type.py`.)
5. Commit the **untracked** e2e draft (`?? e2e/ui-smoke.spec.mjs`, `?? playwright.config.mjs`,
   `?? package.json`), add a `test:e2e` script, and wire a PR-gated CI job. The action is "commit +
   wire," not "wire existing committed tests." Effort M.

**Phase 2 — Decomposition (only after Phase 1 is green)**
6. `backend/council.py` (1292 LOC): extract stage1/stage2/stage3 orchestration, ranking parsing, and
   token-stats into separate modules behind the existing public functions. Effort L.
7. `frontend/src/components/ModelSelector.jsx` (1103 LOC): extract preset logic, filtering, and the
   persisted-selection hook into `utils/` + a custom hook. Effort L.
8. `frontend/src/App.jsx` (712 LOC): extract the SSE event-handling reducer into a
   `useConversationStream` hook (the tests from Phase 1.3 protect this). Effort L.

---

## Open questions / decisions needed

1. **DB storage in production?** B0.4 / B1.4 are HIGH/MED but DB-mode-only (JSON is default). If no
   real deployment uses Postgres/MySQL, these drop to P2. — *gates priority.*
2. **Setup endpoint lockdown:** hard-disable after first run, or require a `SETUP_TOKEN`? This also
   shapes whether T4 (`.env` read-only) becomes unblockable.
3. **JWT 60-day expiry:** intentional for self-hosted convenience, or tighten to 7d + refresh tokens?
4. **Scope of P2 product work:** mobile responsiveness (A2.1), token-cost tracking (A2.2), and
   Docker optional-extras (B2.10) — in scope this cycle, or explicitly deferred?
5. **Untrusted-content marking (B2.3/B2.4):** worth the prompt-budget cost given both are verified
   LOW (self-injection / requires compromised API), or accept the risk?

---

### Honest uncertainty notes
- Severities here follow the skeptic's `verified_severity`. Several original "high" items were
  downgraded (CI dep bypass, e2e-in-CI) and several "medium"s upgraded (XSS, PDF DoS, ranking parser).
- The XSS (B0.2) and untrusted-content (B2.3) items require an attacker-controlled or compromised
  search provider; real sinks, but not trivially user-triggerable.
- The e2e files are currently **untracked** — the plan assumes they get committed as-is first.

---

## Refuted findings (verified FALSE — do not re-open)

These 9 were raised by a finder agent and **rejected** by skeptical verification against source.
Listed so they are not re-discovered and re-litigated later.

| Finding | Why refuted |
|---------|-------------|
| `mem-swallows-exceptions` | `backend/memory.py` exception handling is intentional/correct, not a silent failure. |
| `config-reload-not-thread-safe` | `reload_config()` does not leave requests in the claimed inconsistent state. |
| `runtime-settings-race` | Evidence contained factually wrong claims (e.g. the Windows assertion). |
| `ctx-var-token-stats-shared` | `contextvars` usage in `council.py:18-36` is sound; per-context isolation holds. |
| `react19-defaultprops-broken` | `Toast.jsx` passes props explicitly; no defaultProps breakage under React 19. |
| `errorboundary-incomplete-coverage` | "5 unprotected components" overstated; render-error coverage is adequate. |
| `chatinterface-no-proptypes` | Literally true but cosmetic, not a bug. (Adding propTypes is still tracked as P1 **B1.1** for consistency, not correctness.) |
| `test-async-patch-warnings` | The "coroutine never awaited" warnings are MagicMock auto-spec artifacts in tests, not a production fire-and-forget bug. |
| `message-level-execution-mode-missing` | Not missing — execution mode is overridable at the conversation level by design. |

---

## Provenance

Multi-agent review run 2026-06-18: 6 finder dimensions (security, backend, frontend, tests/CI,
ops/deps, product) → adversarial per-finding verification → synthesis. **50 candidates raised → 41
confirmed → 9 refuted.** Reconciled against PR #17 (remediation Items 01–07), PR #22 (Package C), and
the Jacob feature roadmap so already-fixed/deferred items are excluded. Baseline at review time was
green: backend `pytest` 107 pass + `ruff` clean; frontend `eslint` clean + `vitest` 12 pass.
5 highest-severity items (setup endpoint, DB race, Dockerfile Python drift, XSS href, metadata
clobber) were additionally spot-verified by hand against source.
