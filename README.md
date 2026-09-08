# LLM Council Plus

![LLM Council Plus](header.jpg)

A React/FastAPI application for comparing model answers, peer rankings and a chairman's synthesis. Inspired by [Andrej Karpathy's LLM Council](https://github.com/karpathy/llm-council). Each conversation selects OpenRouter or Ollama, its models, system prompt and execution mode:

| Mode | Stages |
|---|---|
| `chat_only` | Individual model answers |
| `chat_ranking` | Answers and anonymized peer rankings |
| `full` | Answers, rankings and chairman synthesis |

The application supports persistent conversations and attachments, streaming with cancellation and partial-result recovery, administrator-controlled runtime settings, and bounded/idempotent model runs. TOON statistics compare token representations; they are **not provider billing**. Actual provider-reported usage is tracked separately, with missing values left unknown.

This README is the operator guide for the current `main` branch. [VERSION](VERSION) is the authoritative application version; use the deployed Git SHA to identify the exact code revision.

## Operator documentation

- [Run admission, idempotency and resource limits](docs/run-control.md)
- [Administrator permissions and migration](docs/settings-permissions.md)
- [E2E setup and test isolation](e2e/README.md)
- [Reviewed OpenAPI contract](docs/api/openapi.json)
- [Security policy](SECURITY.md) and [contribution guide](CONTRIBUTING.md)

## Installation and first start

Run commands from the repository root unless stated otherwise. Use the committed `uv.lock` and `frontend/package-lock.json` for reproducible dependencies.

### Docker Compose

Requirements: a running Docker engine and current Docker Compose v2. The Compose file uses optional `env_file` entries and the commands below use `--wait`.

```bash
# First installation only; do not overwrite an existing configured .env.
cp .env.example .env
mkdir -p data/conversations credentials
# Edit .env for your provider, users and deployment paths.

docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 180
```

Open **http://localhost**. The frontend nginx proxies `/api/` to the backend. The backend's published port is loopback-only at **http://127.0.0.1:8001**; the frontend port is published on port 80. Configure TLS and access restrictions at your ingress before exposing a shared installation. The optional `production` nginx profile is an additional HTTP proxy, not automatic TLS provisioning.

The `.env` file is required by the supplied Compose `env_file`/bind mount. The backend entrypoint creates the data directory and adjusts `/app/data` ownership to UID/GID 1000; custom mounts must remain writable by the application user. If using the wizard, the mounted `.env` must also be writable by that user; otherwise configure it on the host and recreate the backend.

The Setup Wizard configures a fresh installation. It locks after configuration; an environment-configured Ollama deployment also locks setup at startup. Routine changes belong in environment configuration or the Settings panel, not by reopening setup.

**Current Docker-specific constraints:**

- Both [frontend/nginx.conf](frontend/nginx.conf) and the optional [nginx/nginx.conf](nginx/nginx.conf) still set `client_max_body_size 25m`. A 20 MiB image becomes about 26.7 MiB of base64 in a message, so it can upload successfully and then receive **413 at the proxy**. To support the full API image limit, set `client_max_body_size 40m;` in every active proxy layer and rebuild/reload that layer. Rebuild `frontend` after editing its baked-in nginx config; reload/restart the optional mounted proxy when used. Raising only the backend limit does not change nginx.
- The backend container has a **1 GiB total memory limit** in Compose. PDF workers can each have a 1 GiB virtual-memory ceiling on Linux, with two workers per API process. These are different limits: size the container for the API and concurrent workers, or use a more restrictive processing policy. The worker ceiling is not a guarantee against container OOM.
- The default [backend/Dockerfile](backend/Dockerfile) exports base runtime dependencies only. PostgreSQL requires adding `--extra database` to that `uv export` step and rebuilding the backend image. Finance/embeddings extras similarly require explicit image packaging. Compose does not provision PostgreSQL or MySQL servers.

### Local development

Python **3.10+** is declared by the project; CI and the backend image use **3.12**. Use Node **20.19+** or **22.12+** as required by the locked Vite release (the frontend image uses Node 22; CI tests Node 20). Install `uv` and npm first.

```bash
uv sync --frozen --no-install-project
npm ci --prefix frontend
# First installation only:
cp .env.example .env
mkdir -p data/conversations
```

Terminal 1:

```bash
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

Terminal 2:

```bash
VITE_API_BASE=http://localhost:8001 npm run dev --prefix frontend -- --host localhost --port 5173 --strictPort
```

Open **http://localhost:5173**. Vite does not define an API proxy, so `VITE_API_BASE` is required for this direct-backend setup. In Docker, keep it empty to use the same-origin nginx proxy. It is a frontend build-time setting: changing it for built assets requires a rebuild.

## Provider and access configuration

Use [.env.example](.env.example) as the starting point. Do not commit actual credentials.

### Model providers

```dotenv
# OpenRouter
ROUTER_TYPE=openrouter
OPENROUTER_API_KEY=replace-with-your-key
```

```dotenv
# Ollama running on the same host as a non-container backend
ROUTER_TYPE=ollama
OLLAMA_HOST=localhost:11434
```

`OLLAMA_HOST` is `host:port`, without an `http://` prefix. With Docker Desktop and Ollama on the host, use `host.docker.internal:11434`; on Linux, configure a reachable host address or host-gateway mapping explicitly. Models must already be available in Ollama. `COUNCIL_MODELS` is a comma-separated list of provider model IDs; `CHAIRMAN_MODEL` selects the default chairman. The UI can override both per conversation. Choosing a provider does not silently switch to the other provider on failure.

The Free preset consumes an external ranked feed and falls back to available free-tier models when needed. Availability, provider rate limits and credits must be checked against the provider; a preset is not a capacity guarantee.

Optional search is selected per message. DuckDuckGo requires no key; Tavily, Exa and Brave require their corresponding `ENABLE_*` flag and API key. Google Drive requires `GOOGLE_DRIVE_FOLDER_ID` and a readable service-account file. Finance and embeddings have optional dependency extras:

```bash
# PostgreSQL driver; MySQL driver/RSA support is in the base dependencies.
uv sync --frozen --no-install-project --extra database
# Include every extra required by the installation in its sync command:
uv sync --frozen --no-install-project --extra database --extra finance --extra embeddings
```

### Authentication and administrators

`AUTH_ENABLED=false` is a shared mode: conversations are not isolated by user and runtime settings are writable. For a multi-user installation configure:

```dotenv
AUTH_ENABLED=true
JWT_SECRET=replace-with-a-strong-random-secret
AUTH_USERS='{"Alice":"<bcrypt-hash>","Bob":"<bcrypt-hash>"}'
AUTH_ADMIN_USERS=Alice
```

The values above are placeholders. Generate a secret with `openssl rand -hex 32`; obtain password hashes through the Setup Wizard or the application's bcrypt hashing helper. Legacy plaintext `AUTH_USERS` values are accepted but hashed on load; prefer stored bcrypt hashes.

`AUTH_ADMIN_USERS` is an exact, case-sensitive comma-separated list. **With authentication enabled, an empty list grants nobody permission to change global settings.** Existing installations must explicitly assign administrators. Ordinary users can read/export settings and set their own conversation prompts; the Settings panel is read-only for global mutations.

Settings PATCH/import/reset record actor, version, timestamp and changed field names. API exports omit this audit metadata; retain the backing settings file in backups. Import replaces omitted fields with defaults; PATCH preserves them.

### When to restart or recreate

| Change | Apply it with |
|---|---|
| Runtime prompts/temperatures/search settings through the UI | Saved immediately; subsequently read by requests/stages. Avoid changing them mid-run when reproducibility matters. |
| Provider keys, auth users/admins, database, limits or file paths in environment | Restart local API processes; **recreate** Docker backend containers. |
| Python code/dependencies in Docker | Rebuild and recreate backend. |
| Frontend code, `VITE_API_BASE`, baked-in nginx config | Rebuild and recreate frontend. |
| Mounted outer nginx configuration | Validate and reload/restart that proxy. |

```bash
# After editing environment configuration; restart alone keeps the old container env.
docker compose up -d --force-recreate backend
```

Compose loads `.env` and optional `.env.production` into the container, but explicit `environment:` entries take precedence and their `${...}` interpolation uses the shell/Compose environment file. Keep one deliberate source of deployment values; do not assume editing `.env.production` overrides every setting. `docker compose config --quiet` validates without printing resolved secrets.

## Storage, backups and recovery

### Persistent data map

Paths below assume default settings. Custom paths must be backed up and mounted separately.

| Data | Default host path | Notes |
|---|---|---|
| JSON conversations | `data/conversations/*.json` | `DATABASE_TYPE=json` |
| JSON recovery files | Alongside each conversation: `.bak`, `.lock`, `.corrupt-*`, interrupted `.tmp` files | Stable locks coordinate writers; never remove active locks. Backup is the previous valid version, not full version history. |
| Image attachment bytes | `data/conversations/attachments/<conversation UUID>/<SHA256>` | Required **also with SQL storage**. |
| Run admission/idempotency/usage | `data/run_control.sqlite3` | Default: parent of `DATA_DIR`; override with `RUN_CONTROL_DB`. |
| Runtime settings and audit | `data/runtime_settings.json` and its lock | Override with `RUNTIME_SETTINGS_FILE`; its default does not follow a custom `DATA_DIR`. |
| Optional conversation memory | `data/memory/` relative to API working directory | Separate from the conversation JSON/SQL records. |
| Setup marker | `DATA_DIR/.setup_complete` | Preserve configured setup state. |

Compose mounts `./data` at `/app/data` and fixes `DATA_DIR=/app/data/conversations`. Paths configured outside that mount need their own persistent mount. SQL is selected by `DATABASE_TYPE=postgresql` with `POSTGRESQL_URL`, or `DATABASE_TYPE=mysql` with `MYSQL_URL`. Back up SQL using the database's native consistent dump/snapshot tooling **as well as** attachment, run-control and settings files.

Images are stored separately from JSON; text/PDF attachments retain the **extracted text**, not the original PDF. Downloads enforce conversation ownership. Ollama image input is explicitly rejected. OpenRouter follow-up can reuse the last image batch, within five-image/20 MiB limits. Text context remains bounded; complete archival retention is not the same as sending all history to a model.

### Backup procedure

Drain active runs and stop **all** API writers that share the storage before a filesystem backup. With the default single Compose installation:

```bash
umask 077
backup_dir="backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
git rev-parse HEAD > "$backup_dir/revision.txt"
docker compose stop backend
tar -czf "$backup_dir/data.tar.gz" data
# For SQL: take the corresponding consistent DB backup here as well.
docker compose up -d --wait --wait-timeout 180 backend
tar -tzf "$backup_dir/data.tar.gz" >/dev/null
```

The archive contains private conversations, cached replies and possibly quarantined copies. Restrict and encrypt it. Preserve secret configuration (`.env`, optional production env, Drive credentials) separately in your approved secret/backup store. Add custom `DATA_DIR`, `RUN_CONTROL_DB`, `RUNTIME_SETTINGS_FILE` and memory locations to the backup set when defaults are changed.

Restore into an **empty isolated data directory/database first**, using the recorded code revision and required secrets. Verify conversation reads, attachment downloads, permissions and settings. For a live restore, stop all writers, preserve the current data as a separate rollback copy, replace the complete consistent backup set, restore permissions and then start the API. Do not overlay an old archive onto current data: newer conversations and run records could remain.

A corrupt JSON file with a valid backup is quarantined and recovered on read. Without a valid backup, the API treats it as missing and logs the failure; inspect the retained file and restore from an external backup. Do not create an empty replacement and assume the conversation is recovered.

### Interrupted and repeated runs

Both message endpoints accept UUID `request_id`; the browser generates one per submission. A matching completed retry returns the recorded result without another provider call or message append. Partial retries return the saved partial result; running, failed, aborted or conflicting requests return 409. Inspect persisted progress before deliberately submitting a **new** request ID.

`RUN_CONTROL_DB` must be shared by workers on a local volume supporting SQLite locks. It is not a distributed multi-host coordinator. Do not delete it to clear a busy run: that also removes duplicate-execution protection. After a crashed worker stops renewing its lease, capacity becomes reusable after lease expiry; the old ID remains aborted. Cached replies are cleared when their conversation is deleted, while digest tombstones and non-content usage remain. There is no automatic run-record retention cleanup.

Temporary mode is supported only by the non-stream endpoint: no conversation/reply persistence, but a digest tombstone and usage remain. Its discarded reply cannot be regenerated silently by retrying the same ID. See [run-control semantics](docs/run-control.md) before implementing custom clients.

## Limits and capacity planning

Sizes are binary MiB, even where the UI says MB.

| Setting / resource | Default |
|---|---|
| `MAX_COUNCIL_MODELS` | 5; selected IDs must be unique and nonempty |
| `RUN_MAX_ACTIVE` / `RUN_MAX_USER_ACTIVE` | 8 total / 2 per user; one active run per conversation |
| `RUN_RATE_REQUESTS` / `RUN_RATE_WINDOW_SECONDS` | 20 admitted runs per user per 60 seconds |
| `RUN_LEASE_SECONDS` | 120; live runs renew their leases |
| `MAX_REQUEST_BODY_BYTES` | 41,943,040 bytes (40 MiB), enforced for fixed-length and chunked bodies |
| Ordinary file upload / image upload | 10 MiB / 20 MiB |
| Total message attachment size | 20 MiB of decoded image bytes / UTF-8 text |
| `PDF_MAX_PAGES` | 100 (configurable 1–1000) |
| `PDF_PARSE_TIMEOUT_SECONDS` | 20 seconds (positive, maximum 300) |
| PDF concurrency / extracted output | 2 workers per API process / 50,000 characters |
| PDF process limits | Unix CPU limit; Linux 1 GiB virtual-memory ceiling; no equivalent macOS/Windows memory guarantee |
| `DEFAULT_TIMEOUT` / `STAGE1_TIMEOUT` / `TITLE_GENERATION_TIMEOUT` | 120 / 180 / 180 seconds |

The history builder keeps at most 12 messages, 24,000 characters and an estimated 6,000 history tokens. The provider's tokenizer may differ, and current prompts/attachments add to that history. Stage 2 uses a 90-second collection budget; chairman fallback is capped at two alternative models with a 45-second timeout per attempt. These are not a single end-to-end request deadline.

Failed admitted runs count toward rate limits; rejected requests and idempotent replays do not. Quotas bound concurrency/frequency, not monetary spend. Usage reports count observed provider attempts, including title/fallback/retries; missing prices/tokens remain unknown. Keep upstream billing limits enabled where required.

## Verification and release workflow

### Local checks

```bash
uv sync --frozen --no-install-project
npm ci --prefix frontend
.venv/bin/ruff check backend/ e2e/ tools/check_api_contract.py
.venv/bin/python -m pytest -q
.venv/bin/python tools/check_api_contract.py
npm run lint --prefix frontend
npm run test --prefix frontend
npm run build --prefix frontend
npm audit --audit-level=high --prefix frontend
git diff --check
```

An intentional API change requires review of the generated diff, followed by:

```bash
.venv/bin/python tools/check_api_contract.py --write
```

Do not regenerate the snapshot merely to hide an unexpected contract failure.

### Browser and HTTP E2E

```bash
(cd frontend && npx playwright install chromium)
npm run test:e2e --prefix frontend

# Alternative for a Mac with Chrome installed and port 5175 occupied:
E2E_FRONTEND_PORT=5173 PLAYWRIGHT_CHANNEL=chrome npm run test:e2e --prefix frontend
```

The suite starts fresh frontend/backend/provider processes on ports **5175 / 18765 / 18766** by default and refuses to reuse existing listeners. Only frontend ports 5173/5175 match the current test CORS configuration. Launchers isolate data and credentials; the local HTTP provider is deterministic. Some browser specs deliberately inject API failures; those are distinct from real backend/provider scenarios.

Coverage includes three execution modes, reload/follow-up, stale responses, drafts and delayed uploads, attachments/downloads, EOF/error recovery, idempotent HTTP/SSE replay, admission limits and exact image-size boundaries. Artifacts: `output/e2e-report/` and `output/e2e-results/`. See [E2E documentation](e2e/README.md) for port and executable overrides. The suite does not establish live-cloud model quality or production load capacity.

### PostgreSQL / MySQL integration

Use **dedicated disposable test databases**, never production:

```bash
uv sync --frozen --no-install-project --extra database
# Example local test database credentials only; provision the DB first.
SQL_TEST_URL=postgresql+psycopg2://council:council@127.0.0.1:5432/council_test \
  .venv/bin/python -m pytest backend/tests/test_sql_atomic_updates.py backend/tests/test_sql_http_e2e.py -q

SQL_TEST_URL=mysql+pymysql://council:council@127.0.0.1:3306/council_test \
  .venv/bin/python -m pytest backend/tests/test_sql_atomic_updates.py backend/tests/test_sql_http_e2e.py -q
```

The regular backend suite skips the opt-in live SQL HTTP test without `SQL_TEST_URL`. CI provisions PostgreSQL 16 and MySQL 8.4 and runs both engines, alongside backend checks, frontend checks and browser E2E. Inspect the current [CI workflow](.github/workflows/ci.yml) rather than relying on a historical test count.

### Update and rollback

1. Record the deployed SHA, inspect local changes, drain active requests and take the consistent backup above.
2. In a clean deployment checkout, fetch the reviewed revision (`git pull --ff-only` for an approved `main` update).
3. Check environment/migration notes, sync frozen dependencies for host installs, or rebuild/recreate Compose services:

   ```bash
   docker compose config --quiet
   docker compose up --build -d --wait --wait-timeout 180
   curl --fail --silent --show-error http://127.0.0.1:8001/
   curl --fail --silent --show-error http://127.0.0.1:8001/api/version
   ```

4. Verify login, user isolation, settings permissions, an ordinary message, Stop/recovery and attachment upload/download through the **actual proxy URL**. The Docker healthcheck alone does not exercise these paths.
5. For rollback, deploy the recorded known-good revision and its compatible dependency/image set. Restore the matching data backup only if required by format compatibility, with writers stopped. Keep the failed deployment's data for investigation; do not mix unrelated database and filesystem snapshots.

CI exercises real backend and SQL paths, but does **not** build and test the complete production Compose/nginx topology. The proxy-size and Docker-extra constraints above therefore remain deployment checks.

## Monitoring and troubleshooting

```bash
docker compose ps
docker compose logs --tail 100 backend frontend
docker compose logs -f backend
curl --fail --silent --show-error http://127.0.0.1:8001/
curl --fail --silent --show-error http://127.0.0.1:8001/api/version
```

Monitor HTTP errors/latency, 409/429 rates, pending/partial runs, disk space/inodes, container memory/OOM events and actual provider usage. Avoid routine DEBUG logging of real prompts. Redact credentials and private content before sharing logs or backups.

| Symptom | Check / action |
|---|---|
| Backend won't start | Logs, required `.env`, dependency extras, invalid limits, JWT secret when auth is enabled, DB connectivity and writable mounts. Do not overwrite an existing `.env` as a generic fix. |
| Settings read-only / 403 | Exact `AUTH_ADMIN_USERS` membership; recreate backend after environment changes. |
| Login rejected / 401 | `AUTH_ENABLED`, `AUTH_USERS`, secret and token expiry; frontend clears an expired session. |
| 404 for conversation/attachment | Ownership, conversation existence and recorded attachment membership; inspect corrupt-file recovery logs before assuming deletion. |
| 409 on send | Another active run, existing/aborted ID or changed payload under the same ID. Inspect progress; do not clear the run DB. |
| 429 | Run/user/rate capacity or both PDF slots busy. Honor `Retry-After`; increasing retries can worsen overload. |
| 413 | Compare ingress/nginx and backend body caps. A raw image fits upload limits but its base64 message may exceed nginx's current 25 MiB cap. |
| 400 for PDF/image | Page/time/parse limits, unsupported/encrypted PDF, attachment size/type, or Ollama image rejection. |
| Stream interrupted | Inspect saved partial results, backend/provider errors and proxy timeouts/buffering. A new request ID can incur a new provider charge. |
| UI works but API calls fail in development | Set `VITE_API_BASE`, confirm backend port and allowed localhost origin. |
| E2E startup fails | Free the configured ports or use supported overrides; install Chromium/Chrome; do not point the suite at an existing live instance. |
| OOM / slow PDF | Container budget versus concurrent parser workers; page/time caps; kernel/container OOM logs. |

MIT License — see [LICENSE](LICENSE).
