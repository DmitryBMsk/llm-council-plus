"""
Storage layer with automatic switching between Database (PostgreSQL/MySQL) and JSON files.

Based on DATABASE_TYPE environment variable (Feature 2):
- "postgresql" or "mysql": Use database storage
- "json" (default): Use JSON file storage (backward compatible)
"""

import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from typing import List, Dict, Any, Optional, Generator, Callable
from pathlib import Path
from . import config
from .database import is_using_database, SessionLocal
from .models import Conversation as ConversationModel

logger = logging.getLogger(__name__)


# Cross-platform file locking abstraction
if sys.platform == 'win32':
    # Windows: use msvcrt for file locking
    import msvcrt

    @contextmanager
    def file_lock(file_handle, exclusive: bool = True) -> Generator[None, None, None]:
        """
        Context manager for file locking (Windows implementation using msvcrt).

        Args:
            file_handle: Open file handle
            exclusive: If True, use exclusive lock (for writing). If False, use shared lock (for reading).

        Note: msvcrt.locking() doesn't support true shared locks like POSIX fcntl.
        Both LK_LOCK and LK_RLCK are exclusive locks in msvcrt. For true shared
        lock semantics on Windows, win32file.LockFileEx would be needed.
        We use LK_LOCK for exclusive and LK_RLCK for "shared" (still exclusive
        but indicates intent). This is acceptable for the current use case.
        """
        # Windows msvcrt.locking requires file position and length
        # Lock first byte as a simple file lock
        try:
            # Move to beginning of file
            file_handle.seek(0)
            # LK_LOCK = blocking exclusive lock (value 2)
            # LK_RLCK = blocking read lock (value 3) - Note: still exclusive in msvcrt
            lock_mode = msvcrt.LK_LOCK if exclusive else msvcrt.LK_RLCK
            msvcrt.locking(file_handle.fileno(), lock_mode, 1)
            yield
        finally:
            try:
                file_handle.seek(0)
                msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass  # Ignore unlock errors
else:
    # POSIX (Linux, macOS): use fcntl for file locking
    import fcntl

    @contextmanager
    def file_lock(file_handle, exclusive: bool = True) -> Generator[None, None, None]:
        """
        Context manager for file locking (POSIX implementation using fcntl).

        Args:
            file_handle: Open file handle
            exclusive: If True, use exclusive lock (for writing). If False, use shared lock (for reading).

        Usage:
            with open(path, 'r') as f:
                with file_lock(f, exclusive=False):
                    data = json.load(f)
        """
        lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(file_handle.fileno(), lock_type)
            yield
        finally:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


# ==================== JSON FILE STORAGE (Original) ====================

def ensure_data_dir():
    """Ensure the data directory exists."""
    Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)


def validate_conversation_id(conversation_id: str) -> bool:
    """
    Validate that conversation_id is a valid UUID format.

    Prevents path traversal attacks by ensuring IDs contain only
    safe characters (hex digits and hyphens in UUID format).

    Args:
        conversation_id: The ID to validate

    Returns:
        True if valid UUID format, False otherwise
    """
    import re
    # UUID v4 format: 8-4-4-4-12 hex characters
    uuid_pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
    return bool(re.match(uuid_pattern, conversation_id.lower()))


def get_conversation_path(conversation_id: str) -> str:
    """
    Get the file path for a conversation with path traversal protection.

    Args:
        conversation_id: UUID of the conversation

    Returns:
        Safe file path within DATA_DIR

    Raises:
        ValueError: If conversation_id is invalid or path traversal detected
    """
    # Validate UUID format to prevent path traversal
    if not validate_conversation_id(conversation_id):
        raise ValueError(f"Invalid conversation ID format: {conversation_id}")

    path = os.path.join(config.DATA_DIR, f"{conversation_id}.json")

    # Double-check: ensure resolved path is within DATA_DIR
    real_path = os.path.realpath(path)
    real_data_dir = os.path.realpath(config.DATA_DIR)
    if not real_path.startswith(real_data_dir + os.sep):
        raise ValueError(f"Path traversal detected: {conversation_id}")

    return path


def _json_create_conversation(
    conversation_id: str,
    models: Optional[List[str]] = None,
    chairman: Optional[str] = None,
    username: Optional[str] = None,
    execution_mode: Optional[str] = None,
    router_type: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Create conversation in JSON file with exclusive lock."""
    ensure_data_dir()

    conversation = {
        "id": conversation_id,
        "created_at": datetime.utcnow().isoformat(),
        "title": "New Conversation",
        "messages": [],
        "models": models,
        "chairman": chairman,
        "username": username,
        "execution_mode": execution_mode,
        "router_type": router_type,
        "system_prompt": system_prompt,
    }

    path = get_conversation_path(conversation_id)
    with open(path, 'w') as f:
        with file_lock(f, exclusive=True):
            json.dump(conversation, f, indent=2)

    return conversation


def _json_get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """Get conversation from JSON file with shared lock."""
    path = get_conversation_path(conversation_id)

    if not os.path.exists(path):
        return None

    with open(path, 'r') as f:
        with file_lock(f, exclusive=False):
            return json.load(f)


def _json_save_conversation(conversation: Dict[str, Any]):
    """Save conversation to JSON file with exclusive lock."""
    ensure_data_dir()

    path = get_conversation_path(conversation['id'])
    with open(path, 'w') as f:
        with file_lock(f, exclusive=True):
            json.dump(conversation, f, indent=2)


def _json_update_conversation(conversation_id: str, update_fn: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    """
    Atomically update a JSON conversation under a single exclusive file lock.

    This prevents lost updates when multiple requests concurrently modify the same
    conversation (read-modify-write must be a single critical section).
    """
    ensure_data_dir()
    path = get_conversation_path(conversation_id)
    if not os.path.exists(path):
        raise ValueError(f"Conversation {conversation_id} not found")

    # Use one file handle + one exclusive lock for the full read-modify-write cycle.
    with open(path, "r+", encoding="utf-8") as f:
        with file_lock(f, exclusive=True):
            f.seek(0)
            conversation = json.load(f)
            update_fn(conversation)
            f.seek(0)
            f.truncate()
            json.dump(conversation, f, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # Best-effort: fsync may not be available on some platforms/filesystems.
                pass

            return conversation


def _json_list_conversations() -> List[Dict[str, Any]]:
    """List all conversations from JSON files with shared locks."""
    ensure_data_dir()

    conversations = []
    for filename in os.listdir(config.DATA_DIR):
        if filename.endswith('.json'):
            path = os.path.join(config.DATA_DIR, filename)
            try:
                with open(path, 'r') as f:
                    with file_lock(f, exclusive=False):
                        data = json.load(f)
                        conversations.append({
                            "id": data["id"],
                            "created_at": data["created_at"],
                            "title": data.get("title", "New Conversation"),
                            "message_count": len(data["messages"]),
                            "username": data.get("username")
                        })
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Skipping malformed conversation file %s: %s", filename, e)
                continue

    conversations.sort(key=lambda x: x["created_at"], reverse=True)
    return conversations


def _json_delete_conversation(conversation_id: str) -> bool:
    """Delete conversation from JSON file."""
    path = get_conversation_path(conversation_id)

    if not os.path.exists(path):
        return False

    os.remove(path)
    return True


def _json_delete_all_conversations():
    """Delete all conversations from JSON files."""
    ensure_data_dir()

    for filename in os.listdir(config.DATA_DIR):
        if filename.endswith('.json'):
            path = os.path.join(config.DATA_DIR, filename)
            os.remove(path)


# ==================== DATABASE STORAGE (Feature 2) ====================

def _db_create_conversation(
    conversation_id: str,
    models: Optional[List[str]] = None,
    chairman: Optional[str] = None,
    username: Optional[str] = None,
    execution_mode: Optional[str] = None,
    router_type: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Create conversation in database."""
    models_payload: Any = models
    if execution_mode is not None or router_type is not None or system_prompt is not None:
        models_payload = {"models": models, "execution_mode": execution_mode, "router_type": router_type, "system_prompt": system_prompt}

    db = SessionLocal()
    try:
        conversation = ConversationModel(
            id=conversation_id,
            title="New Conversation",
            messages=[],
            models=models_payload,
            chairman=chairman,
            username=username
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation.to_dict()
    finally:
        db.close()


def _db_get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """Get conversation from database."""
    db = SessionLocal()
    try:
        conversation = db.query(ConversationModel).filter(
            ConversationModel.id == conversation_id
        ).first()

        if conversation is None:
            return None

        return conversation.to_dict()
    finally:
        db.close()


def _db_save_conversation(conversation: Dict[str, Any]):
    """Save conversation to database."""
    db = SessionLocal()
    try:
        db_conversation = db.query(ConversationModel).filter(
            ConversationModel.id == conversation['id']
        ).first()

        if db_conversation:
            db_conversation.title = conversation.get('title', 'New Conversation')
            db_conversation.messages = conversation.get('messages', [])
            models_value: Any = conversation.get('models')
            if conversation.get("execution_mode") is not None or conversation.get("router_type") is not None:
                models_value = {
                    "models": models_value,
                    "execution_mode": conversation.get("execution_mode"),
                    "router_type": conversation.get("router_type"),
                }
            db_conversation.models = models_value
            db_conversation.chairman = conversation.get('chairman')
            db_conversation.username = conversation.get('username')
            db.commit()
    finally:
        db.close()


def _db_list_conversations() -> List[Dict[str, Any]]:
    """List all conversations from database."""
    db = SessionLocal()
    try:
        conversations = db.query(ConversationModel).order_by(
            ConversationModel.created_at.desc()
        ).all()

        return [
            {
                "id": conv.id,
                "created_at": conv.created_at.isoformat() if conv.created_at else "",
                "title": conv.title or "New Conversation",
                "message_count": len(conv.messages) if conv.messages else 0,
                "username": conv.username
            }
            for conv in conversations
        ]
    finally:
        db.close()


def _db_delete_conversation(conversation_id: str) -> bool:
    """Delete conversation from database."""
    db = SessionLocal()
    try:
        conversation = db.query(ConversationModel).filter(
            ConversationModel.id == conversation_id
        ).first()

        if conversation is None:
            return False

        db.delete(conversation)
        db.commit()
        return True
    finally:
        db.close()


def _db_delete_all_conversations():
    """Delete all conversations from database."""
    db = SessionLocal()
    try:
        db.query(ConversationModel).delete()
        db.commit()
    finally:
        db.close()


# ==================== UNIFIED API (Auto-switches based on DATABASE_TYPE) ====================

def create_conversation(
    conversation_id: str,
    models: Optional[List[str]] = None,
    chairman: Optional[str] = None,
    username: Optional[str] = None,
    execution_mode: Optional[str] = None,
    router_type: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new conversation.

    Args:
        conversation_id: Unique identifier for the conversation
        models: Optional list of council model IDs
        chairman: Optional chairman/judge model ID
        username: Optional username of the user who created the conversation
        system_prompt: Optional system prompt for the conversation (e.g., TTCC mode)

    Returns:
        New conversation dict
    """
    if is_using_database():
        conv = _db_create_conversation(conversation_id, models, chairman, username, execution_mode, router_type, system_prompt)
    else:
        conv = _json_create_conversation(conversation_id, models, chairman, username, execution_mode, router_type, system_prompt)

    return _normalize_conversation(conv)


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        Conversation dict or None if not found
    """
    if is_using_database():
        conv = _db_get_conversation(conversation_id)
    else:
        conv = _json_get_conversation(conversation_id)

    return _normalize_conversation(conv) if conv else None


def save_conversation(conversation: Dict[str, Any]):
    """
    Save a conversation to storage.

    Args:
        conversation: Conversation dict to save
    """
    if is_using_database():
        _db_save_conversation(_normalize_conversation(conversation))
    else:
        _json_save_conversation(conversation)


def _infer_router_type_from_models(models: Optional[List[str]]) -> Optional[str]:
    if not models:
        return None
    for model_id in models:
        if isinstance(model_id, str) and "/" in model_id:
            return "openrouter"
    return "ollama"


def _normalize_conversation(conversation: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Normalize conversation shape for backwards compatibility.

    Supports:
    - Legacy DB format where `models` is a list
    - New DB format where `models` is a dict: {"models": [...], "execution_mode": "...", "router_type": "..."}
    - JSON format with top-level `execution_mode`
    """
    if not conversation:
        return conversation

    models = conversation.get("models")
    if isinstance(models, dict):
        # Extract embedded settings without changing DB schema.
        conversation = conversation.copy()
        conversation["execution_mode"] = conversation.get("execution_mode") or models.get("execution_mode")
        conversation["router_type"] = conversation.get("router_type") or models.get("router_type")
        conversation["system_prompt"] = conversation.get("system_prompt") or models.get("system_prompt")
        conversation["models"] = models.get("models")

    # Backwards compatibility: infer router_type if missing.
    if not conversation.get("router_type"):
        inferred = _infer_router_type_from_models(conversation.get("models"))
        conversation = conversation.copy()
        conversation["router_type"] = inferred or config.ROUTER_TYPE

    return conversation


def list_conversations() -> List[Dict[str, Any]]:
    """
    List all conversations (metadata only).

    Returns:
        List of conversation metadata dicts
    """
    if is_using_database():
        return _db_list_conversations()
    return _json_list_conversations()


def add_user_message(conversation_id: str, content: str):
    """
    Add a user message to a conversation.

    Args:
        conversation_id: Conversation identifier
        content: User message content
    """
    if is_using_database():
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        conversation["messages"].append({
            "role": "user",
            "content": content
        })

        save_conversation(conversation)
        return

    def _update(conv: Dict[str, Any]) -> None:
        conv.setdefault("messages", []).append({
            "role": "user",
            "content": content
        })

    _json_update_conversation(conversation_id, _update)


def add_assistant_message(
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: Optional[List[Dict[str, Any]]] = None,
    stage3: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    Add an assistant message to a conversation.

    Supports partial execution modes where Stage 2 and/or Stage 3 may be omitted.

    Args:
        conversation_id: Conversation identifier
        stage1: List of individual model responses
        stage2: List of model rankings (optional)
        stage3: Final synthesized response (optional)
        metadata: Optional metadata including label_to_model and aggregate_rankings
    """
    message = {
        "role": "assistant",
        "stage1": stage1,
    }

    if stage2 is not None:
        message["stage2"] = stage2
    if stage3 is not None:
        message["stage3"] = stage3

    if metadata:
        message["metadata"] = metadata

    if is_using_database():
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        conversation["messages"].append(message)
        save_conversation(conversation)
        return

    def _update(conv: Dict[str, Any]) -> None:
        conv.setdefault("messages", []).append(message)

    _json_update_conversation(conversation_id, _update)


def update_conversation_title(conversation_id: str, title: str):
    """
    Update the title of a conversation.

    Args:
        conversation_id: Conversation identifier
        title: New title for the conversation
    """
    if is_using_database():
        conversation = get_conversation(conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")

        conversation["title"] = title
        save_conversation(conversation)
        return

    def _update(conv: Dict[str, Any]) -> None:
        conv["title"] = title

    _json_update_conversation(conversation_id, _update)


def delete_conversation(conversation_id: str) -> bool:
    """
    Delete a conversation.

    Args:
        conversation_id: Conversation identifier

    Returns:
        True if deleted, False if not found
    """
    if is_using_database():
        return _db_delete_conversation(conversation_id)

    path = get_conversation_path(conversation_id)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def delete_all_conversations():
    """Delete all conversations."""
    if is_using_database():
        _db_delete_all_conversations()
    else:
        _json_delete_all_conversations()
