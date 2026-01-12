FROM python:3.12-slim

WORKDIR /app

# Install system dependencies including gosu for privilege dropping
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    gosu \
    && rm -rf /var/lib/apt/lists/* \
    && gosu nobody true

# Create non-root user for security
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Copy requirements first for better caching
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy VERSION file to /app
COPY VERSION /app/VERSION

# Copy application code into backend package
COPY backend/ /app/backend/

# Copy and prepare entrypoint script
COPY backend/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create data directory with correct permissions (will be overwritten by bind mount)
RUN mkdir -p /app/data/conversations \
    && chown -R appuser:appgroup /app

# Note: We don't use USER here because entrypoint runs as root
# to fix bind mount permissions, then drops to appuser via gosu

# Expose port
EXPOSE 8001

# Health check (runs as root but checks the app which runs as appuser)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8001/')" || exit 1

# Use entrypoint to handle permissions and user switching
ENTRYPOINT ["/app/entrypoint.sh"]
