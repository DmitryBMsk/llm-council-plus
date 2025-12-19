# How to Run LLM Council

Quick start guide to get LLM Council running on your machine.

---

## Prerequisites

### Required:
- **Python 3.10+** ([Download](https://python.org))
- **Node.js 18+** ([Download](https://nodejs.org))
- **uv** - Python package manager ([Install](https://docs.astral.sh/uv/))

### Optional (for database):
- **PostgreSQL 12+** (if using PostgreSQL storage)
- **MySQL 8+** (if using MySQL storage)

---

## Quick Start (5 minutes)

### 1. Get OpenRouter API Key
1. Go to [https://openrouter.ai](https://openrouter.ai)
2. Sign up for a free account
3. Generate API key
4. Add credits ($5 recommended for testing)

### 2. Clone & Setup
```bash
# Clone repository
git clone <your-repo-url>
cd llm-council

# Install backend dependencies
uv sync

# Install frontend dependencies
cd frontend
npm install
cd ..
```

### 3. Configure Environment
```bash
# Copy example environment file
cp .env.example .env

# Edit .env and add your OpenRouter API key
nano .env  # or use any text editor
```

**Required in `.env`:**
```bash
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

### 4. Run the Application

**Option A: Two Terminals (Recommended)**

Terminal 1 - Backend:
```bash
uv run python -m backend.main
```

Terminal 2 - Frontend:
```bash
cd frontend
npm run dev
```

**Option B: Background Processes**
```bash
# Start backend in background
uv run python -m backend.main &

# Start frontend
cd frontend
npm run dev
```

### 5. Open Application
Open your browser to: **http://localhost:5173**

---

## Configuration Options

### Storage Backend

**JSON (Default - Zero Setup):**
```bash
DATABASE_TYPE=json
```

**PostgreSQL:**
```bash
DATABASE_TYPE=postgresql
POSTGRESQL_URL=postgresql+psycopg2://user:password@localhost:5432/llmcouncil
```

**MySQL:**
```bash
DATABASE_TYPE=mysql
MYSQL_URL=mysql+pymysql://user:password@localhost:3306/llmcouncil
```

### Feature Flags

**Feature 4: Tools & Memory**
```bash
# All free tools enabled by default
# (Calculator, Wikipedia, ArXiv, DuckDuckGo, Yahoo Finance)

# Optional: Paid tools
ENABLE_TAVILY=false
TAVILY_API_KEY=

# Memory system (free local embeddings)
ENABLE_MEMORY=true

# Optional: Better embeddings
ENABLE_OPENAI_EMBEDDINGS=false
OPENAI_API_KEY=

# Advanced: LangGraph workflows
ENABLE_LANGGRAPH=false
```

---

## Detailed Setup

### Database Setup (Optional)

If using PostgreSQL or MySQL instead of JSON:

**PostgreSQL:**
```bash
# Install PostgreSQL
brew install postgresql  # macOS
# or apt-get install postgresql  # Linux

# Start PostgreSQL
brew services start postgresql

# Create database
createdb llmcouncil

# Update .env
DATABASE_TYPE=postgresql
POSTGRESQL_URL=postgresql+psycopg2://your_user:your_password@localhost:5432/llmcouncil
```

**MySQL:**
```bash
# Install MySQL
brew install mysql  # macOS
# or apt-get install mysql-server  # Linux

# Start MySQL
brew services start mysql

# Create database
mysql -u root -p
CREATE DATABASE llmcouncil;
exit;

# Update .env
DATABASE_TYPE=mysql
MYSQL_URL=mysql+pymysql://root:your_password@localhost:3306/llmcouncil
```

**Auto Initialization:**
- Tables are created automatically on first run
- No manual schema setup needed

---

## Development Mode

### Backend Development
```bash
# Run with auto-reload
uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8001
```

### Frontend Development
```bash
cd frontend
npm run dev
# Vite auto-reloads on file changes
```

### View Logs
```bash
# Backend logs
uv run python -m backend.main 2>&1 | tee backend.log

# Check logs
tail -f backend.log
```

---

## Testing

### Test Backend API
```bash
# Health check
curl http://localhost:8001/

# List conversations
curl http://localhost:8001/api/conversations

# Create conversation
curl -X POST http://localhost:8001/api/conversations \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Test Frontend
1. Open http://localhost:5173
2. Click "+ New Conversation"
3. Type a question
4. Watch 3-stage council process
5. See final answer

### Test Features

**Test Delete:**
1. Hover over conversation → click ⋮
2. Click "Delete"
3. Confirm

**Test Edit Title:**
1. Hover over conversation → click ⋮
2. Click "Edit title"
3. Type new title → press Enter

**Test Tools:**
- Ask: "What's the price of AAPL stock?"
- Ask: "Calculate 12345 * 67890"
- Ask: "Search for latest AI news"

---

## Troubleshooting

### Port Already in Use
```bash
# Kill process on port 8001 (backend)
lsof -ti:8001 | xargs kill -9

# Kill process on port 5173 (frontend)
lsof -ti:5173 | xargs kill -9
```

### Backend Won't Start
```bash
# Check Python version
python --version  # Must be 3.10+

# Reinstall dependencies
rm -rf .venv
uv sync
```

### Frontend Won't Start
```bash
# Check Node version
node --version  # Must be 18+

# Reinstall dependencies
cd frontend
rm -rf node_modules package-lock.json
npm install
```

### Database Connection Error
```bash
# Check database is running
psql -l  # PostgreSQL
mysql -u root -p  # MySQL

# Verify connection string in .env
# Format: protocol://user:password@host:port/database
```

### API Key Issues
```bash
# Verify API key in .env
cat .env | grep OPENROUTER_API_KEY

# Test API key manually
curl https://openrouter.ai/api/v1/models \
  -H "Authorization: Bearer YOUR_KEY_HERE"
```

### Memory/Tools Not Working
```bash
# Check dependencies installed
uv pip list | grep -E "langchain|chromadb|sentence-transformers"

# Reinstall if missing
uv sync
```

---

## Production Deployment

### Environment Setup
```bash
# Use production API keys
OPENROUTER_API_KEY=your-production-key

# Use database (not JSON)
DATABASE_TYPE=postgresql
POSTGRESQL_URL=your-production-db-url

# Security
SECRET_KEY=your-secret-key  # Add if implementing auth
```

### Build Frontend
```bash
cd frontend
npm run build
# Serves from dist/ folder
```

### Run Production Backend
```bash
# Use production ASGI server
pip install gunicorn
gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8001
```

### Serve Frontend
```bash
# Option 1: Nginx
# Configure nginx to serve frontend/dist/

# Option 2: Node static server
npm install -g serve
serve -s frontend/dist -l 5173
```

---

## Docker Deployment (Optional)

### Backend Dockerfile
```dockerfile
FROM python:3.10
WORKDIR /app
COPY . .
RUN pip install uv && uv sync
CMD ["uv", "run", "python", "-m", "backend.main"]
EXPOSE 8001
```

### Frontend Dockerfile
```dockerfile
FROM node:18
WORKDIR /app
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build
CMD ["npm", "run", "preview"]
EXPOSE 5173
```

### Docker Compose
```yaml
version: '3.8'
services:
  backend:
    build: .
    ports:
      - "8001:8001"
    env_file:
      - .env
    depends_on:
      - db

  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    ports:
      - "5173:5173"

  db:
    image: postgres:15
    environment:
      POSTGRES_DB: llmcouncil
      POSTGRES_PASSWORD: your_password
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

Run:
```bash
docker-compose up -d
```

---

## Performance Tips

### Backend:
- Use PostgreSQL/MySQL instead of JSON for better performance
- Enable database connection pooling
- Use Redis for caching (future feature)
- Set `ENABLE_MEMORY=false` if not needed

### Frontend:
- Build for production: `npm run build`
- Enable gzip compression
- Use CDN for static assets
- Implement lazy loading

---

## Monitoring

### Check System Status
```bash
# Backend health
curl http://localhost:8001/

# Database connections
# PostgreSQL: SELECT * FROM pg_stat_activity;
# MySQL: SHOW PROCESSLIST;
```

### View Storage Info
```bash
# JSON mode
ls -lh data/conversations/

# Database mode
# Check via psql/mysql CLI
```

### Monitor API Usage
- Check OpenRouter dashboard for usage
- Monitor token consumption
- Track TOON savings

---

## Support

### Common Commands Reference
```bash
# Start backend
uv run python -m backend.main

# Start frontend
cd frontend && npm run dev

# View logs
tail -f backend.log

# Reset database (PostgreSQL)
dropdb llmcouncil && createdb llmcouncil

# Clear conversations (JSON mode)
rm -rf data/conversations/*

# Update dependencies
uv sync && cd frontend && npm install
```

### Get Help
- Check documentation in `contributions/` folder
- Review `.env.example` for configuration options
- Open issue on GitHub

---

## Quick Commands Summary

```bash
# 🚀 QUICK START (Copy-paste these 5 commands)
uv sync                                    # Install backend
cd frontend && npm install && cd ..        # Install frontend
cp .env.example .env                       # Create config
# Edit .env and add OPENROUTER_API_KEY
uv run python -m backend.main &            # Start backend
cd frontend && npm run dev                 # Start frontend (opens browser)
```

**Access:** http://localhost:5173

---

## System Requirements

**Minimum:**
- 2 CPU cores
- 4GB RAM
- 2GB disk space

**Recommended:**
- 4+ CPU cores
- 8GB+ RAM
- 10GB disk space (for database)

**Platform:**
- macOS, Linux, Windows (WSL2)
- Docker (optional)
