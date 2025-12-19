# LLM Council Plus - Features

## Overview
LLM Council Plus is a multi-model AI system that combines responses from multiple AI models through a democratic voting process, delivering superior answers through collective intelligence.

---

## Core Features

### 🎯 **3-Stage Council Process**
The heart of LLM Council - a democratic approach to AI responses:

1. **Stage 1: Individual Responses**
   - Multiple AI models respond independently to your question
   - Each model brings its unique perspective and strengths
   - Responses are collected in parallel for speed

2. **Stage 2: Peer Ranking**
   - Each model evaluates and ranks all responses anonymously
   - Blind peer review eliminates model bias
   - Aggregate rankings determine the best answers

3. **Stage 3: Final Synthesis**
   - Chairman model synthesizes insights from all stages
   - Combines best aspects of top-ranked responses
   - Delivers a comprehensive, well-reasoned answer

**Models Used (configurable):**
- Council Members: Any models from OpenRouter's 100+ model catalog
- Default: `openai/gpt-5.1`, `anthropic/claude-sonnet-4.5`, `google/gemini-3-pro-preview`, `x-ai/grok-4`
- Chairman: `google/gemini-3-pro-preview` (configurable)
- Browse all available models at [openrouter.ai/models](https://openrouter.ai/models)

---

## Feature 1: TOON Integration

### 📦 **Token Optimization via TOON Format**
TOON (Token-Oriented Object Notation) reduces token usage by 20-60% compared to JSON.

**How It Works:**
TOON is a compact data serialization format that combines:
- YAML-style indentation for structure
- CSV-like tabular layouts for arrays
- Minimal punctuation and whitespace

**Applied to All Council Stages:**
- **Stage 1→2**: Responses converted to TOON for peer review
- **Stage 2→3**: Rankings converted to TOON for chairman synthesis
- **Conversation history**: Context compressed with TOON

**Benefits:**
- **Cost savings**: 20-60% fewer tokens = lower API costs
- **Faster responses**: Less data to process
- **Real-time stats**: UI shows token savings after each query

**Token Stats Display:**
After Stage 3 completes, a green badge shows:
- Total saved percentage
- JSON tokens → TOON tokens
- Hover for per-stage breakdown

**Technical Details:**
- Uses `python-toon` library for encoding
- Token counting via `tiktoken` (OpenAI tokenizer)
- Graceful fallback to JSON if TOON unavailable

---

## Feature 2: Database Migration

### 💾 **Multi-Database Storage Backend**
Flexible storage with automatic switching based on configuration.

**Supported Backends:**
- **JSON Files** (default) - Zero setup, works immediately
- **PostgreSQL** - Production-ready, ACID compliant
- **MySQL** - Popular, widely supported

**Key Features:**
- Unified storage API - same code works with all backends
- Automatic database initialization
- SQLAlchemy models for PostgreSQL/MySQL
- Environment variable configuration (`DATABASE_TYPE`)

**Storage Schema:**
```sql
conversations (
  id VARCHAR(36) PRIMARY KEY,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  title VARCHAR(500),
  messages JSON  -- Native JSONB in PostgreSQL
)
```

---

## Feature 3: Follow-up Questions with Context

### 💬 **Conversation Memory & Context**
Natural multi-turn conversations with full context awareness.

**How It Works:**
- Last 6 messages (3 exchanges) sent as context
- Context passed to all council members
- Enables follow-up questions and clarifications
- Seamless conversation continuity

**Benefits:**
- "What about X?" style questions work naturally
- Models understand conversation history
- No need to repeat previous information
- Smarter, context-aware responses

---

## Feature 4: Advanced AI Capabilities

### 🛠️ **Tool Integration**
5 free tools + 2 optional paid tools for enhanced capabilities.

**FREE Tools (Always Available):**
1. **Calculator** - Safe AST-based math evaluator (supports sqrt, sin, cos, log, etc.)
2. **Wikipedia** - Factual information lookup
3. **ArXiv** - Research paper search
4. **DuckDuckGo** - Web search for current info
5. **Yahoo Finance** - Stock prices and market data

**PAID Tools (Optional):**
- **Tavily** - Advanced web search (requires API key)
- **Exa** - AI-powered neural search with semantic understanding (requires API key)

**Auto-Detection:**
- System detects when tools are needed
- Automatically selects appropriate tool
- Results fed into council discussion
- Tool outputs shown in metadata

---

## Feature 5: Conversation Management

### 🗑️ **Delete Conversations**
Remove unwanted conversations with confirmation.

**Features:**
- 3-dot menu (⋮) for actions
- Confirmation dialog before deletion
- Works with all storage backends
- Auto-clears current conversation if deleted

### ✏️ **Edit Conversation Titles**
Inline title editing for better organization.

**Features:**
- Click ✏️ in 3-dot menu
- Inline text input appears
- Press Enter to save, Escape to cancel
- Real-time UI updates across all views

**Keyboard Shortcuts:**
- `Enter` - Save changes
- `Escape` - Cancel editing

### 💬 **Temporary Chat Mode**
Private conversations that don't save to storage.

**Use Cases:**
- Sensitive queries
- Quick one-off questions
- Testing without cluttering history

**Implementation:**
- Backend API ready (`temporary: true` flag)
- No storage persistence
- No title generation
- No memory tracking

---

## Additional Features

### 🧙 **Setup Wizard**
First-time configuration made easy:
- Choose LLM provider (OpenRouter or Ollama)
- Enter API keys securely
- Configure optional authentication
- Enable Tavily web search
- Hot reload - no container restart needed

### 📎 **File Upload**
Attach files to your queries:
- **Supported formats:** PDF, TXT, MD, JPG, PNG, GIF, WebP
- **Size limits:** 10MB for documents, 5MB for images
- Content extracted and sent to all council members
- Multiple files per message

### 🔐 **Authentication System**
Optional user authentication:
- JWT-based with 60-day token expiry
- Multiple users with separate passwords
- User filtering in conversation sidebar
- Auto-logout on token expiry

### 🎨 **Modern UI/UX**
- Clean, professional dark theme interface
- Real-time streaming responses (SSE)
- Stage-by-stage progress indicators with timing
- Token savings display
- SVG logo design (council nodes)

### 🔒 **Privacy & Security**
- Local-first JSON storage option
- Optional database backends
- Temporary chat mode for sensitive data
- No data leaves your server (except API calls to AI providers)

### ⚡ **Performance**
- Parallel API calls to all models
- Streaming responses for instant feedback
- TOON compression saves 30-60% tokens
- Efficient database queries with indexes

### 🔧 **Configuration**
- Environment variable based setup
- Flag-based feature control
- Easy API key management
- Multiple storage backend options

---

## Technical Stack

### Backend:
- **FastAPI** - High-performance async API framework
- **SQLAlchemy** - ORM for database operations
- **LangChain** - Tool integration framework
- **ChromaDB** - Vector database for memory
- **TOON** - Token-efficient data format

### Frontend:
- **React** - UI library
- **Vite** - Build tool and dev server
- **Server-Sent Events** - Real-time streaming

### AI/ML:
- **OpenRouter** - Multi-model API gateway
- **HuggingFace** - Free local embeddings
- **Sentence Transformers** - Text embedding models

---

## Configuration Flags

### Database:
```bash
DATABASE_TYPE=json          # json, postgresql, or mysql
POSTGRESQL_URL=...          # If using PostgreSQL
MYSQL_URL=...               # If using MySQL
```

### Feature 4 - Tools & Web Search:
```bash
# Free tools (always enabled)
# - Calculator, Wikipedia, ArXiv, DuckDuckGo, Yahoo Finance

# Paid web search tools (optional - choose one)
ENABLE_TAVILY=false         # Traditional web search
TAVILY_API_KEY=

ENABLE_EXA=false            # AI-powered neural search
EXA_API_KEY=
```

---

## Feature Comparison

| Feature | Free Tier | Premium (Optional) |
|---------|-----------|-------------------|
| 3-Stage Council | ✅ | ✅ |
| Full OpenRouter Catalog | ✅ | ✅ |
| Ollama Local Models | ✅ | ✅ |
| TOON Compression | ✅ | ✅ |
| Database Storage | ✅ | ✅ |
| Context Memory | ✅ | ✅ |
| Calculator | ✅ | ✅ |
| Wikipedia | ✅ | ✅ |
| ArXiv Search | ✅ | ✅ |
| DuckDuckGo Search | ✅ | ✅ |
| Yahoo Finance | ✅ | ✅ |
| Conversation Management | ✅ | ✅ |
| File Attachments | ✅ | ✅ |
| Tavily Search | ❌ | ✅ (API key) |
| Exa AI Search | ❌ | ✅ (API key) |

---

## Roadmap

### Completed Features:
- [x] Export conversations (Markdown)
- [x] Custom model selection (via Setup Wizard)
- [x] Multi-user support (authentication system)
- [x] Dark mode
- [x] File upload (PDF, TXT, MD, images)
- [x] Google Drive integration
- [x] Setup Wizard for configuration
- [x] Hot reload (config changes without restart)

### Planned Features:
- [ ] Memory system (ChromaDB vector store for conversation recall)
- [ ] LangGraph workflows (graph-based orchestration)
- [ ] Conversation folders/tags
- [ ] Export to PDF
- [ ] Prompt templates
- [ ] API usage statistics
- [ ] Mobile responsive design
- [ ] Keyboard shortcuts
- [ ] Conversation search

### Potential Integrations:
- [ ] More AI providers (Groq, Together AI)
- [ ] More tools (Google Scholar, WolframAlpha)
- [ ] Voice input/output
- [ ] Image generation
- [ ] Code execution sandbox

---

## Credits

**Inspired by:** [Andrej Karpathy's llm-council](https://github.com/karpathy/llm-council)

**Core Technologies:**
- OpenRouter for multi-model API access (100+ models)
- TOON format for token optimization
- LangChain for tool orchestration
- Exa for AI-powered neural search

**Open Source Libraries:**
- FastAPI, React, SQLAlchemy, Vite
- tiktoken for token counting

---

## License & Contributing

This is an open-source project. Contributions welcome!

**Key Features for Contributors:**
- Clean, modular architecture
- Storage backend abstraction
- Flag-based feature control
- Docker-first development
- Professional code standards

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.
