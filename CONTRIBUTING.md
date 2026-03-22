# Contributing to LLM Council Plus

## Local Development

### Prerequisites

- Docker and Docker Compose
- Python 3.10+ (for backend development)
- Node.js 20+ (for frontend development)

### Quick Start

```bash
# Start everything in Docker
APP_VERSION="1.3.1" docker compose up -d --build

# Access at http://localhost
```

### Backend Development

```bash
# Create virtual environment
uv venv .venv

# Install dependencies
uv pip install ruff pytest pytest-asyncio --python .venv/bin/python
uv pip install fastapi uvicorn python-dotenv httpx pydantic sqlalchemy \
  psycopg2-binary pymysql python-multipart pyjwt bcrypt --python .venv/bin/python

# Run tests
.venv/bin/python -m pytest -q

# Lint
.venv/bin/ruff check backend/
```

### Frontend Development

```bash
cd frontend
npm install
npm run dev       # Dev server
npm run lint      # ESLint
npm run build     # Production build
npm run test      # Vitest
```

## Quality Gates

All PRs must pass:

- **Backend:** `ruff check backend/` + `pytest -q` (90+ tests)
- **Frontend:** `npm run lint` (0 errors) + `npm run build` + `npm run test`

These checks run automatically in CI via GitHub Actions.

## Versioning

The `VERSION` file at the project root is the single source of truth.
`pyproject.toml` and `frontend/package.json` must match.

## Commit Style

Use conventional commits: `fix:`, `feat:`, `refactor:`, `chore:`, `docs:`.
Keep subject line under 72 chars, imperative mood.
