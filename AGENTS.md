# Repository Guidelines

## Project Structure & Module Organization
- `backend/` is the FastAPI service; `backend/main.py` exposes the ASGI app, `council.py` and `openrouter.py` handle model orchestration, `tools.py`/`memory.py` house optional features, and `database.py` abstracts storage. Tests live in `backend/tests/test_*.py`.  
- `frontend/` is a Vite + React client; entry is `src/main.jsx`, UI components are under `src/components`, shared state under `src/store`, and styles in `src/App.css`/`src/index.css`. Build output lands in `frontend/dist/`.  
- Data defaults to JSON under `data/conversations/`; Docker, deploy, and ops helpers are in `deploy/`, `docker-compose.yml`, `start.sh`, and `nginx/`. Top-level scripts (`main.py`, `RUN.md`) document manual and Docker flows.

## Build, Test, and Development Commands
- Install deps: `uv sync` (backend) and `cd frontend && npm install`.  
- Run locally: `uv run python -m backend.main` (or `uv run uvicorn backend.main:app --reload`) and `npm run dev` from `frontend/`. Use `./start.sh` to boot both.  
- Build: `npm run build` for production assets; Docker: `docker compose up --build`.  
- Tests: `uv run pytest backend/tests` for backend coverage; lint JS with `npm run lint`.

## Coding Style & Naming Conventions
- Python: follow PEP 8, snake_case for modules/functions, PascalCase for classes, and prefer typed signatures plus concise docstrings for public APIs. Keep async paths non-blocking.  
- JavaScript/React: functional components with hooks; 2-space indent; camelCase for vars/functions, PascalCase for components. ESLint (`npm run lint`) enforces recommended + React Hooks rules and flags unused vars (except intentional ALL_CAPS constants).  
- Keep config/env access centralized (e.g., `.env`, `backend/config.py`) and avoid hardcoded secrets or paths.

## Testing Guidelines
- Add or extend `backend/tests/test_*.py` with pytest; name tests descriptively and mock external HTTP calls (see `test_openrouter.py`) to avoid live API hits.  
- For UI changes, run `npm run build` and spot-check core flows: new conversation, multi-stage responses, tool-invocation prompts. Document any manual steps in the PR.  
- Aim for meaningful assertions over branches; include async tests with `@pytest.mark.asyncio` where relevant.

## Commit & Pull Request Guidelines
- Commit style follows Conventional Commits seen in history (`feat:`, `fix:`, `docs:`). Keep commits scoped and readable.  
- PRs should include: a concise summary, testing notes (commands run, screenshots/GIFs for UI), linked issues, and any env/db changes required.  
- Avoid committing `.env` or credential files; scrub conversation logs before sharing.

## Security & Configuration Tips
- Copy `.env.example` to `.env` and keep keys (e.g., `OPENROUTER_API_KEY`) out of git. Use `ROUTER_TYPE=ollama` for local models or set `COUNCIL_MODELS`/`CHAIRMAN_MODEL` explicitly.  
- Choose storage intentionally: default JSON in `data/conversations/` or configure `DATABASE_TYPE` with proper URLs for Postgres/MySQL.  
- When testing tools or memory features, ensure optional dependencies from `pyproject.toml` are installed via `uv sync`.***
