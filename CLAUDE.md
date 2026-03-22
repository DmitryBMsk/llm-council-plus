# CLAUDE.md - Technical Notes for LLM-TTCC-TEAM-PRO

This file contains technical details, architectural decisions, and important implementation notes for future development sessions.

## Project Overview

LLM-TTCC-TEAM-PRO is a 3-stage deliberation system where multiple LLMs collaboratively answer user questions. The key innovation is anonymized peer review in Stage 2, preventing models from playing favorites.

**Application Name:** LLM-TTCC-TEAM-PRO

## Architecture

### Deployment

The application runs entirely in Docker containers:
- **Frontend:** Nginx serving React app on port 80 (HTTP by default)
- **Backend:** FastAPI Python app on port 8001

```bash
# Start the application
APP_VERSION="1.2.12" docker compose up -d

# Access at http://localhost
```

### Backend Structure (`backend/`)

**`config.py`**
- Contains `COUNCIL_MODELS` (list of OpenRouter model identifiers)
- Contains `CHAIRMAN_MODEL` (model that synthesizes final answer)
- Contains `reload_config()` function for hot reload without container restart
- Supports both OpenRouter (cloud) and Ollama (local) models
- Configuration loaded from `.env` file

**`auth.py`**
- JWT-based authentication system
- `reload_auth()` function for hot reload of auth configuration
- Users configured via `AUTH_USERS_JSON` environment variable
- 60-day token expiry with auto-logout

**`openrouter.py`**
- `query_model()`: Single async model query
- `query_models_parallel()`: Parallel queries using `asyncio.gather()`
- `query_models_streaming()`: SSE streaming for real-time responses
- Uses dynamic config access (`config.OPENROUTER_API_KEY`) for hot reload support
- Graceful degradation: returns None on failure, continues with successful responses

**`council.py`** - The Core Logic
- `stage1_collect_responses()`: Parallel queries to all council models
- `stage2_collect_rankings()`:
  - Anonymizes responses as "Response A, B, C, etc."
  - Creates `label_to_model` mapping for de-anonymization
  - Prompts models to evaluate and rank (with strict format requirements)
  - Returns tuple: (rankings_list, label_to_model_dict)
  - Each ranking includes both raw text and `parsed_ranking` list
- `stage3_synthesize_final()`: Chairman synthesizes from all responses + rankings
- `parse_ranking_from_text()`: Extracts "FINAL RANKING:" section
- `calculate_aggregate_rankings()`: Computes average rank position

**`storage.py`**
- JSON-based conversation storage in `data/conversations/`
- Each conversation: `{id, created_at, messages[], username}`
- Assistant messages contain: `{role, stage1, stage2, stage3}`
- Thread-safe with file locking

**`main.py`**
- FastAPI app with CORS enabled
- SSE streaming endpoints for real-time responses
- Setup wizard endpoint (`POST /api/setup/config`)
- Hot reload triggers after setup config save

### Frontend Structure (`frontend/src/`)

**`App.jsx`**
- Main orchestration: manages conversations list and current conversation
- Shows SetupWizard if not configured
- Shows LoginScreen if auth enabled and not authenticated
- Handles message sending with SSE streaming

**`components/SetupWizard.jsx`**
- First-time configuration UI
- Configures: LLM provider (OpenRouter/Ollama), API keys, Tavily, Authentication
- Saves to `.env` file and triggers hot reload

**`components/LoginScreen.jsx`**
- JWT-based authentication
- User selection or manual username input
- SVG logo (council nodes design)

**`components/Sidebar.jsx`**
- Conversation list with user filter
- 3-dot menu for edit/delete
- Inline title editing
- SVG logo with "LLM-TTCC-TEAM-PRO" text

**`components/ChatInterface.jsx`**
- Multiline textarea (3 rows, resizable)
- Enter to send, Shift+Enter for new line
- File upload support (PDF, TXT, MD, images)
- Web search toggle (requires Tavily)
- Google Drive upload button
- Real-time streaming display

**`components/Stage1.jsx`, `Stage2.jsx`, `Stage3.jsx`**
- Tab views for each stage of council deliberation
- Real-time updates during streaming
- ReactMarkdown rendering

**Styling**
- Dark theme (CSS variables in `index.css`)
- Primary color: #4a90e2 (blue)
- SVG logos for sidebar and login

## Key Features

### Hot Reload
Configuration changes via Setup Wizard are applied without container restart:
- `reload_config()` in config.py reloads all environment variables
- `reload_auth()` in auth.py reloads JWT and user settings
- Dynamic config access in openrouter.py (`config.OPENROUTER_API_KEY`)

### Authentication (Optional)
- JWT tokens with 60-day expiry
- Users defined via `AUTH_USERS_JSON` env var
- Enable/disable via `AUTH_ENABLED` flag
- Auto-logout on token expiry

### File Upload
- Supports: PDF, TXT, MD, JPG, PNG, GIF, WebP
- Size limits: 10MB files, 5MB images
- Content extracted and sent to council

### Web Search (Tavily)
- Optional Tavily API integration
- Toggle per-message in chat interface
- Search results fed to Stage 1 queries

### Google Drive Integration
- Upload conversation exports to Drive
- Requires `credentials/google-credentials.json`
- Configure `GOOGLE_DRIVE_FOLDER_ID`

### Export
- Export to Markdown format
- Download or upload to Google Drive

## Key Design Decisions

### Stage 2 Prompt Format
The Stage 2 prompt is very specific to ensure parseable output:
```
1. Evaluate each response individually first
2. Provide "FINAL RANKING:" header
3. Numbered list format: "1. Response C", "2. Response A", etc.
4. No additional text after ranking section
```

### De-anonymization Strategy
- Models receive: "Response A", "Response B", etc.
- Backend creates mapping: `{"Response A": "openai/gpt-5.1", ...}`
- Frontend displays model names in **bold** for readability
- This prevents bias while maintaining transparency

### SSE Streaming
- Real-time response streaming via Server-Sent Events
- Chunk buffering handles split JSON messages
- Graceful fallback on connection errors

## Port Configuration
- **Frontend:** 80 (HTTP, redirects to HTTPS), 443 (HTTPS)
- **Backend:** 8001

## Docker Volumes
```yaml
volumes:
  - ./data/conversations:/app/data/conversations  # Conversation storage
  - ./credentials:/app/credentials:ro              # Google Drive creds
  - ./.env:/app/.env                               # Hot reload support
```

## Environment Variables

### Required
- `OPENROUTER_API_KEY` - OpenRouter API key (or use Ollama)

### Optional
- `ROUTER_TYPE` - "openrouter" (default) or "ollama"
- `AUTH_ENABLED` - "true" to enable authentication
- `JWT_SECRET` - Secret for JWT tokens
- `AUTH_USERS_JSON` - JSON object of username:password pairs
- `TAVILY_API_KEY` - For web search feature
- `GOOGLE_DRIVE_FOLDER_ID` - For Drive integration
- `COUNCIL_MODELS` - Comma-separated model list
- `CHAIRMAN_MODEL` - Model for final synthesis

## Common Gotchas

1. **Hot Reload**: After using Setup Wizard, config is reloaded automatically
2. **CORS Issues**: Frontend must match allowed origins in CORS middleware
3. **Docker Restart**: Use `docker compose up -d`, not `docker restart`
4. **HTTPS**: If you enable HTTPS in nginx, ensure certs are mounted correctly

## Data Flow Summary

```
User Query
    ↓
Stage 1: Parallel queries → [individual responses] (SSE streaming)
    ↓
Stage 2: Anonymize → Parallel ranking queries → [evaluations + parsed rankings]
    ↓
Aggregate Rankings Calculation → [sorted by avg position]
    ↓
Stage 3: Chairman synthesis with full context
    ↓
Return: {stage1, stage2, stage3, metadata}
    ↓
Frontend: Display with tabs + validation UI
```

The entire flow is async/parallel where possible to minimize latency.
