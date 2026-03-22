#!/bin/bash

# LLM-TTCC-TEAM-PRO - Stop script
# Kills all running app processes and frees up all related ports

echo "============================================"
echo "  LLM-TTCC-TEAM-PRO - Shutting down..."
echo "============================================"
echo ""

KILLED=0

# --------------------------------------------------
# 1. Kill backend processes (uvicorn / FastAPI on port 8001)
# --------------------------------------------------
echo "[1/4] Stopping backend processes..."
for PORT in 8000 8001 8002 8003; do
    PIDS=$(lsof -ti:$PORT 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "  Killing processes on port $PORT: $PIDS"
        echo "$PIDS" | xargs kill -9 2>/dev/null || true
        KILLED=$((KILLED + 1))
    fi
done

# Also kill any uvicorn processes related to this app
UVICORN_PIDS=$(pgrep -f "uvicorn backend.main" 2>/dev/null || true)
if [ -n "$UVICORN_PIDS" ]; then
    echo "  Killing uvicorn processes: $UVICORN_PIDS"
    echo "$UVICORN_PIDS" | xargs kill -9 2>/dev/null || true
    KILLED=$((KILLED + 1))
fi

# Kill any "python -m backend.main" processes
PYTHON_PIDS=$(pgrep -f "python -m backend.main" 2>/dev/null || true)
if [ -n "$PYTHON_PIDS" ]; then
    echo "  Killing python backend processes: $PYTHON_PIDS"
    echo "$PYTHON_PIDS" | xargs kill -9 2>/dev/null || true
    KILLED=$((KILLED + 1))
fi
echo ""

# --------------------------------------------------
# 2. Kill frontend processes (Vite dev server on ports 5173+)
# --------------------------------------------------
echo "[2/4] Stopping frontend processes..."
for PORT in 5173 5174 5175 5176 5177 5178 5179 5180; do
    PIDS=$(lsof -ti:$PORT 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "  Killing processes on port $PORT: $PIDS"
        echo "$PIDS" | xargs kill -9 2>/dev/null || true
        KILLED=$((KILLED + 1))
    fi
done

# Also kill any vite processes
VITE_PIDS=$(pgrep -f "vite" 2>/dev/null || true)
if [ -n "$VITE_PIDS" ]; then
    echo "  Killing vite processes: $VITE_PIDS"
    echo "$VITE_PIDS" | xargs kill -9 2>/dev/null || true
    KILLED=$((KILLED + 1))
fi
echo ""

# --------------------------------------------------
# 3. Kill nginx proxy if running (port 8080)
# --------------------------------------------------
echo "[3/4] Stopping proxy processes..."
for PORT in 80 8080; do
    PIDS=$(lsof -ti:$PORT 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "  Killing processes on port $PORT: $PIDS"
        echo "$PIDS" | xargs kill -9 2>/dev/null || true
        KILLED=$((KILLED + 1))
    fi
done
echo ""

# --------------------------------------------------
# 4. Stop Docker containers if running
# --------------------------------------------------
echo "[4/4] Stopping Docker containers (if running)..."
if command -v docker &> /dev/null; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
        docker compose -f "$SCRIPT_DIR/docker-compose.yml" down 2>/dev/null && echo "  Docker containers stopped." || true
    fi
else
    echo "  Docker not installed, skipping."
fi
echo ""

# --------------------------------------------------
# Summary
# --------------------------------------------------
if [ $KILLED -gt 0 ]; then
    echo "============================================"
    echo "  ✓ LLM-TTCC-TEAM-PRO has been stopped."
    echo "    Cleaned up $KILLED process group(s)."
    echo "============================================"
else
    echo "============================================"
    echo "  No running LLM-TTCC-TEAM-PRO processes found."
    echo "============================================"
fi
