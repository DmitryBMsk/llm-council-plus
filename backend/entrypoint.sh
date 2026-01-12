#!/bin/bash
set -e

# Entrypoint script for llm-council backend
# Ensures data directories exist with correct permissions before starting the app
# Runs as root initially to fix permissions, then drops to appuser

DATA_DIR="${DATA_DIR:-/app/data/conversations}"
APP_USER="appuser"
APP_GROUP="appgroup"

# Function to fix permissions
fix_permissions() {
    echo "Ensuring data directory exists: $DATA_DIR"
    mkdir -p "$DATA_DIR"

    # Fix ownership of data directory for appuser
    chown -R "$APP_USER:$APP_GROUP" /app/data

    echo "Permissions fixed for $DATA_DIR"
}

# If running as root, fix permissions and switch to appuser
if [ "$(id -u)" = "0" ]; then
    fix_permissions

    # Use gosu to drop privileges and run as appuser
    exec gosu "$APP_USER" python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001
else
    # Already running as non-root (for development or testing)
    # Just check if directory exists and is writable
    if [ ! -d "$DATA_DIR" ]; then
        echo "Creating data directory: $DATA_DIR"
        mkdir -p "$DATA_DIR" || {
            echo "ERROR: Cannot create data directory: $DATA_DIR"
            echo "Please ensure the directory has correct permissions."
            echo "Run on host: mkdir -p ./data/conversations && chmod 777 ./data/conversations"
            echo "Or: sudo chown -R 1000:1000 ./data"
            exit 1
        }
    fi

    if [ ! -w "$DATA_DIR" ]; then
        echo "ERROR: Cannot write to data directory: $DATA_DIR"
        echo "Please ensure the directory has correct permissions."
        echo "Run on host: sudo chown -R 1000:1000 ./data"
        exit 1
    fi

    exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001
fi
