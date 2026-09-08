# Reproducible browser regression suite

Run from the project root after `uv sync --frozen --no-install-project`:

```sh
npm ci --prefix frontend
(cd frontend && npx playwright install chromium)
npm run test:e2e --prefix frontend
```

On a Mac with Google Chrome already installed, skip browser download and use:

```sh
PLAYWRIGHT_CHANNEL=chrome npm run test:e2e --prefix frontend
```

The suite starts fresh frontend, backend and Ollama/OpenRouter-compatible HTTP provider
processes. It refuses to reuse existing listeners. Defaults: frontend 5175,
backend 18765, provider 18766. If 5175 is occupied, set
`E2E_FRONTEND_PORT=5173` (both frontend origins are allowed by the app's CORS
policy). Backend/provider ports can be changed with `E2E_BACKEND_PORT` and
`E2E_PROVIDER_PORT`; custom Python executable uses `E2E_PYTHON`.

Service launchers clear inherited secrets, disable Python dotenv, point Vite at
an empty env directory, disable auth/tools/memory, seed the external model catalog locally, and place app data/settings in
a temporary directory. Tests call the real browser SSE client, backend routes,
JSON persistence and local HTTP provider; they do not call paid LLMs. The
provider records actual model request payloads for context and system-prompt
assertions. API-mocked browser regression specs intentionally cover client fault
injection separately from the full-stack specs.

`full-stack.spec.js` verifies three execution modes, reload and follow-up context,
plus browser council creation. CI runs both browser and unit suites. Browser
failure artifacts live under `output/e2e-report` and `output/e2e-results`, uploaded
by GitHub Actions even when tests fail.

SQL concurrency tests run against real PostgreSQL 16 and MySQL 8.4 CI services
with `SQL_TEST_URL`, using the optional `database` dependency extra. Local database
equivalent (only point at a disposable test database):

```sh
uv sync --frozen --no-install-project --extra database
SQL_TEST_URL=postgresql+psycopg2://council:council@127.0.0.1:5432/council_test \
  .venv/bin/python -m pytest backend/tests/test_sql_atomic_updates.py -q
```

No live cloud-model quality, real Drive account, or production load claim is
implied by this suite. Traces can contain test prompts and fixture payloads only.
