#!/bin/bash

# LLM-TTCC-TEAM-PRO - Start script
# Installs all dependencies, then starts backend and frontend

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  LLM-TTCC-TEAM-PRO - Starting up..."
echo "============================================"
echo ""

# --------------------------------------------------
# 1. Check prerequisites
# --------------------------------------------------
echo "[1/4] Checking prerequisites..."

if ! command -v uv &> /dev/null; then
    echo "ERROR: 'uv' is not installed."
    echo "Install it: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo "ERROR: 'node' is not installed."
    echo "Install Node.js 18+: https://nodejs.org"
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo "ERROR: 'npm' is not installed."
    echo "Install Node.js 18+: https://nodejs.org"
    exit 1
fi

echo "  uv:   $(uv --version 2>/dev/null || echo 'installed')"
echo "  node: $(node --version)"
echo "  npm:  $(npm --version)"
echo ""

# --------------------------------------------------
# 2. Install backend dependencies
# --------------------------------------------------
echo "[2/4] Installing backend dependencies (uv sync)..."
uv sync
echo "  Dependencies installed (includes LangChain tools)."

# Try optional extras that have native build deps and may fail on some platforms.
if uv sync --extra finance 2>/dev/null; then
    echo "  Yahoo Finance (yfinance) installed."
else
    echo "  NOTE: Skipping yfinance (curl-cffi build failed on this platform)."
fi

if uv sync --extra embeddings 2>/dev/null; then
    echo "  Embeddings installed (chromadb + sentence-transformers)."
else
    echo "  NOTE: Skipping embeddings (torch not available on this platform)."
fi
echo ""

# --------------------------------------------------
# 3. Install frontend dependencies
# --------------------------------------------------
echo "[3/4] Installing frontend dependencies (npm install)..."
cd frontend
npm install
cd "$SCRIPT_DIR"
echo ""

# --------------------------------------------------
# 4. Create .env if missing
# --------------------------------------------------
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "NOTE: No .env file found. Copying .env.example to .env"
        echo "      Edit .env to add your API keys before using the app."
        cp .env.example .env
    else
        echo "WARNING: No .env file found. The app may not work without configuration."
    fi
    echo ""
fi

# --------------------------------------------------
# 5. Start services
# --------------------------------------------------
echo "[4/4] Starting services..."
echo ""

# Start backend
echo "  Starting backend on http://localhost:8001..."
uv run python -m backend.main &
BACKEND_PID=$!

# Wait for backend to be ready
sleep 2

# Start frontend
echo "  Starting frontend on http://localhost:5173..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"

echo ""
echo "============================================"
echo "  ✓ LLM-TTCC-TEAM-PRO is running!"
echo ""
echo "  Backend:  http://localhost:8001"
echo "  Frontend: http://localhost:5173"
echo ""
echo "  Press Ctrl+C to stop both servers"
echo "  Or run ./stop.sh from another terminal"
echo "============================================"

# Cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down LLM-TTCC-TEAM-PRO..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo "Done."
    exit 0
}

trap cleanup SIGINT SIGTERM

# Wait for child processes
wait
