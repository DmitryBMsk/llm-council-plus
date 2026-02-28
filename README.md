# LLM-TTCC-TEAM-PRO

![llmcouncil](header.jpg)

> **Inspired by [Andrej Karpathy's LLM Council](https://github.com/karpathy/llm-council)** - see his [original tweet](https://x.com/karpathy/status/1992381094667411768) about the concept.

The idea of this repo is that instead of asking a question to your favorite LLM provider (e.g. OpenAI GPT 5.1, Google Gemini 3.0 Pro, Anthropic Claude Sonnet 4.5, xAI Grok 4, etc.), you can group them into your "LLM-TTCC-TEAM-PRO" council. This is a containerized web app with a Setup Wizard that guides you through configuration. It uses OpenRouter to send your query to multiple LLMs, asks them to review and rank each other's work, and finally a Chairman LLM produces the final response.

In a bit more detail, here is what happens when you submit a query:

1. **Stage 1: First opinions**. The user query is given to all LLMs individually, and the responses are collected. The individual responses are shown in a "tab view", so that the user can inspect them all one by one.
2. **Stage 2: Review**. Each individual LLM is given the responses of the other LLMs. Under the hood, the LLM identities are anonymized so that the LLM can't play favorites when judging their outputs. The LLM is asked to rank them in accuracy and insight.
3. **Stage 3: Final response**. The designated Chairman takes all of the model's responses and compiles them into a single final answer that is presented to the user.

## Technical Training Course Creator (TTCC) Mode

LLM-TTCC-TEAM-PRO includes a built-in **Technical Training Course Creator** mode that transforms the council into an enterprise-grade course generation system. When TTCC mode is selected, a specialized system prompt is injected into all council models, turning them into expert instructional designers.

### TTCC Features

- **5-Phase Workflow**: Intake, Research, Architecture, Content Generation, QA
- **Enterprise Deliverables**: Slide decks, hands-on labs, quizzes, and instructor guides
- **Web Search Integration**: Auto-enables web search for current technical accuracy
- **Multi-LLM Validation**: Council models cross-validate course content for accuracy
- **Course Levels**: Beginner, Intermediate, and Advanced calibration
- **Source Material Support**: Upload PDFs, markdown, or images as reference material

### How to Use TTCC Mode

1. Click **"New Conversation"** to open the Model Selector
2. Select your council models (multimodal models recommended)
3. Under **"System Prompt Mode"**, select **"Technical Training Course Creator (TTCC)"**
4. Web search will auto-enable for content validation
5. Start your conversation with a course request, e.g.:
   > "Create an intermediate-level, 2-day course on Kubernetes on Azure AKS for DevOps engineers with 2+ years experience"

The TTCC system prompt is defined in [`Technical_Training_Course_Creator_System_Prompt.md`](Technical_Training_Course_Creator_System_Prompt.md).

## What's Different from the Original

This fork extends [Andrej Karpathy's llm-council](https://github.com/karpathy/llm-council) with production-ready features:

| Feature | Original | LLM-TTCC-TEAM-PRO |
|---------|----------|------------------|
| **Deployment** | Manual Python/npm setup | Docker Compose (one command) |
| **Configuration** | Edit config.py manually | Visual Setup Wizard |
| **Models** | 4 hardcoded models | Full OpenRouter catalog (100+ models) |
| **Local Models** | ❌ | ✅ Ollama support |
| **Authentication** | ❌ | ✅ JWT multi-user system |
| **Storage** | JSON files only | JSON, PostgreSQL, MySQL |
| **Token Optimization** | ❌ | ✅ TOON format (20-60% savings) |
| **Web Search** | ❌ | ✅ DuckDuckGo + Tavily + Exa + Brave |
| **File Attachments** | ❌ | ✅ PDF, TXT, MD, MDX, images (drag-and-drop) |
| **System Prompts** | ❌ | ✅ Per-conversation system prompts (General / TTCC / Custom) |
| **Tools** | ❌ | ✅ Calculator, Wikipedia, ArXiv, Yahoo Finance |
| **Real-time Streaming** | Basic | SSE with heartbeats & state persistence |
| **Error Handling** | Silent failures | Toast notifications + visual indicators |
| **Hot Reload** | ❌ | ✅ Config changes without restart |
| **Conversation Search** | ❌ | ✅ Filter by title with relative dates |
| **Stage Timeouts** | ❌ | ✅ 90s stage-level timeout (first-N-complete) |

### Recent Updates (v1.4.0)

| New Feature | What it adds | Where |
|---|---|---|
| **TTCC Mode** | Technical Training Course Creator system prompt with 5-phase course generation workflow | Model Selector → System Prompt Mode |
| **System Prompt Presets** | Per-conversation system prompts: General, TTCC, or Custom | Model Selector → System Prompt Mode |
| **Drag-and-Drop Upload** | Drop files directly onto the chat area with visual overlay feedback | Chat Interface |
| **MDX File Support** | Upload `.mdx` files alongside PDF, TXT, MD, and images | File Upload |
| **Auto Web Search** | TTCC mode auto-enables web search for content validation | Chat Interface |

### Recent Updates (v1.3.1)

| New Feature | What it adds | Where |
|---|---|---|
| **Per-conversation router** | Choose **OpenRouter** or **Ollama** per conversation (no fallback) | Model Selector → Router |
| **Model presets + council sizing** | Built-in presets + saved presets, configurable council size, “I’m Feeling Lucky” | Model Selector |
| **Runtime Settings panel** | Edit prompts + temperatures; **persist / reset / export / import** (no secrets) | Settings → Prompts/Temps/Backup |
| **Stop / Abort streaming** | Cancel an in-flight request cleanly (frontend abort + backend task cancel) | Composer “Stop” |
| **Web search provider selection** | DuckDuckGo (free) + Tavily + Exa + Brave, per-message selection | Composer search pill |
| **Full-article fetch (optional)** | Fetch top-N pages via Jina Reader for richer context (DDG/Brave) | Settings → Web Search |
| **Search context panel** | Compact view (title + domain) + expandable content per result | Assistant message UI |
| **UI polish pass** | Dark dropdown menus, cleaner sidebar actions, compact composer layout | App UI |

### Recent Updates (v1.3.0)

- **Conversation Search** — Filter conversations by title in real-time
- **Relative Dates** — Sidebar shows "Today 14:30", "Yesterday", "Mon", "Jan 2" etc.
- **Stage-level Timeouts** — Stage 2/3 proceed after 90s with partial results (first-N-complete pattern)
- **Toast Notifications** — Visual alerts for model timeouts and errors
- **Improved Error Handling** — Graceful fallback when models fail or timeout

## Quick Start

**Easiest way — use the Setup Wizard:**
```bash
# 1. Create your .env file (REQUIRED — backend will crash without it)
cp .env.example .env

# 2. Create the data directory for conversation storage
mkdir -p data/conversations

# 3. Build and start (first time — full rebuild recommended)
docker compose build --no-cache && docker compose up -d

# 4. Open http://localhost
#    The Setup Wizard will guide you through configuration
```

> **Important:** Steps 1 and 2 are required before the first run. Without the `.env` file and `data/` directory, the backend container will crash-loop.

The Setup Wizard lets you:
- Choose LLM provider (OpenRouter or Ollama)
- Enter API keys
- Optionally enable authentication
- Optionally configure web search (Tavily or Exa)

**Alternative: Manual configuration**
```bash
cp .env.example .env
mkdir -p data/conversations
# Edit .env with your API keys (see examples below)
docker compose up --build -d
# Open http://localhost
```

> **Note:** Authentication is disabled by default for easy setup. For production deployment with user authentication, see [SECURITY.md](SECURITY.md).

## Vibe Code Alert

This project was 99% vibe coded as a fun Saturday hack because I wanted to explore and evaluate a number of LLMs side by side in the process of [reading books together with LLMs](https://x.com/karpathy/status/1990577951671509438). It's nice and useful to see multiple responses side by side, and also the cross-opinions of all LLMs on each other's outputs. I'm not going to support it in any way, it's provided here as is for other people's inspiration and I don't intend to improve it. Code is ephemeral now and libraries are over, ask your LLM to change it in whatever way you like.

## Detailed Setup

### 1. Install Dependencies

The project uses [uv](https://docs.astral.sh/uv/) for project management.

**Backend:**
```bash
uv sync
```

**Frontend:**
```bash
cd frontend
npm install
cd ..
```

### 2. Configure API Key

Create a `.env` file in the project root:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

Get your API key at [openrouter.ai](https://openrouter.ai/). Make sure to purchase the credits you need, or sign up for automatic top up.

Alternatively, you can use Ollama for local models by setting `ROUTER_TYPE=ollama` in your `.env` file (see below).

Models are selected via the Setup Wizard or dynamically in the UI. Browse all available models at [openrouter.ai/models](https://openrouter.ai/models).

## Running the Application

### Docker (Recommended)

> **Prerequisite:** Docker Desktop must be running on your machine before executing any `docker compose` commands.

```bash
# First-time setup or after dependency changes — full rebuild (no cache)
docker compose build --no-cache && docker compose up -d

# Regular start (uses cached layers, faster)
docker compose up --build -d

# Access the application at http://localhost
```

Backend API is available at http://localhost:8001

**Stopping and managing containers:**
```bash
# Stop and remove all containers
docker compose down

# View running containers
docker compose ps

# View backend logs (useful for debugging)
docker compose logs backend

# Follow logs in real-time
docker compose logs -f backend
```

**Troubleshooting**

**Backend crash-looping** (`Restarting (1)` in `docker compose ps`):
```bash
# Check the error logs first
docker compose logs backend --tail 50

# Most common cause: missing .env file or data directory
cp .env.example .env        # if .env doesn't exist
mkdir -p data/conversations  # if data/ doesn't exist
docker compose down
docker compose up -d
```

**`ModuleNotFoundError` or import errors:**

Docker's build cache is likely stale. Force a full rebuild:
```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

### Development Mode (without Docker)

Terminal 1 (Backend):
```bash
uv run python -m backend.main
```

Terminal 2 (Frontend):
```bash
cd frontend
npm run dev
```

Then open http://localhost:5173 in your browser.

## Common Configuration

### OpenRouter (cloud)
```bash
ROUTER_TYPE=openrouter
OPENROUTER_API_KEY=sk-or-v1-...
```

### Ollama (local)
```bash
ROUTER_TYPE=ollama
```

If you're running the backend in Docker and Ollama is running on your host machine, set:
```bash
OLLAMA_HOST=host.docker.internal:11434
```

## Web Search (Optional)

The UI can run web search and inject results into Stage 1 as context. You can select the provider per message (search pill) or set a default in Settings. In TTCC mode, web search is auto-enabled for content validation.

Providers:
- **DuckDuckGo (free)**: enabled by default, no API key required
- **Tavily / Exa / Brave**: require API keys (optional)

Enable any of the optional providers:
```bash
ENABLE_TAVILY=true
TAVILY_API_KEY=tvly-...
```

or:
```bash
ENABLE_EXA=true
EXA_API_KEY=...
```

or:
```bash
ENABLE_BRAVE=true
BRAVE_API_KEY=...
```

## Storage

Default storage is local JSON files under `data/conversations/` (mounted into the backend container).

Database storage is supported via `DATABASE_TYPE=postgresql` or `DATABASE_TYPE=mysql` (see `backend/storage.py`).

## Tech Stack

- **Backend:** FastAPI (Python 3.10+), async httpx, OpenRouter API or Ollama
- **Frontend:** React + Vite, react-markdown for rendering
- **Storage:** JSON files in `data/conversations/` (optional DB storage)
- **Package Management:** uv for Python, npm for JavaScript

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## Security

See [SECURITY.md](SECURITY.md) for security considerations and reporting vulnerabilities.

## License

MIT License - see [LICENSE](LICENSE) for details.
