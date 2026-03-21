"""FastAPI backend for LLM Council — application bootstrap."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import os

# Configure logging based on LOG_LEVEL env var (default: INFO)
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)

logger = logging.getLogger(__name__)

from .api.deps import VERSION
from .auth import validate_jwt_config
from .database import init_database

# --- Import routers ---
from .api.routes.settings import router as settings_router
from .api.routes.setup import router as setup_router
from .api.routes.auth_routes import router as auth_router
from .api.routes.models import router as models_router
from .api.routes.conversations import router as conversations_router
from .api.routes.drive import router as drive_router

app = FastAPI(title="LLM Council API")

# Initialize on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database and validate configuration at startup."""
    # Validate JWT configuration if auth is enabled
    validate_jwt_config()
    # Initialize database tables if using database storage (Feature 2: Multi-DB support)
    init_database()

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5175", "http://localhost:3000", "http://localhost", "https://localhost", "http://127.0.0.1", "http://127.0.0.1:80"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API", "version": VERSION}


@app.get("/api/version")
async def get_api_version():
    """Get API version."""
    return {"version": VERSION}


# --- Register routers ---
app.include_router(settings_router)
app.include_router(setup_router)
app.include_router(auth_router)
app.include_router(models_router)
app.include_router(conversations_router)
app.include_router(drive_router)


# --- Backward-compatible imports for tests ---
# Tests import these names from backend.main; keep them accessible here.
from .api.routes.conversations import (  # noqa: F401, E402
    send_message_stream,
    create_conversation,
    SendMessageRequest,
    CreateConversationRequest,
    Conversation,
    ConversationMetadata,
    UpdateTitleRequest,
    FileAttachment,
    separate_attachments,
    build_query_with_attachments,
)
from .api.routes.settings import UpdateRuntimeSettingsRequest  # noqa: F401, E402
from .api.routes.setup import SetupConfigRequest  # noqa: F401, E402
from .api.routes.drive import DriveUploadRequest  # noqa: F401, E402
from .api.deps import (  # noqa: F401, E402
    get_current_user,
    get_optional_user,
    _ownership_username,
    security,
    get_version,
)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT") or os.getenv("BACKEND_PORT") or "8001")
    uvicorn.run(app, host="0.0.0.0", port=port)
