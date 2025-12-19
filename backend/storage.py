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
from typing import List, Dict, Any, Optional, Generator
from pathlib import Path
from .config import DATA_DIR, DATABASE_TYPE
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
        """
        # Windows msvcrt.locking requires file position and length
        # Lock first byte as a simple file lock
        try:
            # Move to beginning of file
            file_handle.seek(0)
            # LK_NBLCK = non-blocking exclusive lock, LK_NBRLCK = non-blocking shared lock
            # Using LK_LOCK (blocking) for simplicity
            lock_mode = msvcrt.LK_LOCK if exclusive else msvcrt.LK_LOCK
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
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


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

    path = os.path.join(DATA_DIR, f"{conversation_id}.json")

    # Double-check: ensure resolved path is within DATA_DIR
    real_path = os.path.realpath(path)
    real_data_dir = os.path.realpath(DATA_DIR)
    if not real_path.startswith(real_data_dir + os.sep):
        raise ValueError(f"Path traversal detected: {conversation_id}")

    return path


def _json_create_conversation(
    conversation_id: str,
    models: Optional[List[str]] = None,
    chairman: Optional[str] = None,
    username: Optional[str] = None
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
        "username": username
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


def _json_list_conversations() -> List[Dict[str, Any]]:
    """List all conversations from JSON files with shared locks."""
    ensure_data_dir()

    conversations = []
    for filename in os.listdir(DATA_DIR):
        if filename.endswith('.json'):
            path = os.path.join(DATA_DIR, filename)
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

    for filename in os.listdir(DATA_DIR):
        if filename.endswith('.json'):
            path = os.path.join(DATA_DIR, filename)
            os.remove(path)


# ==================== DATABASE STORAGE (Feature 2) ====================

def _db_create_conversation(
    conversation_id: str,
    models: Optional[List[str]] = None,
    chairman: Optional[str] = None,
    username: Optional[str] = None
) -> Dict[str, Any]:
    """Create conversation in database."""
    db = SessionLocal()
    try:
        conversation = ConversationModel(
            id=conversation_id,
            title="New Conversation",
            messages=[],
            models=models,
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
            db_conversation.models = conversation.get('models')
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
    username: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new conversation.

    Args:
        conversation_id: Unique identifier for the conversation
        models: Optional list of council model IDs
        chairman: Optional chairman/judge model ID
        username: Optional username of the user who created the conversation

    Returns:
        New conversation dict
    """
    if is_using_database():
        return _db_create_conversation(conversation_id, models, chairman, username)
    return _json_create_conversation(conversation_id, models, chairman, username)


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        Conversation dict or None if not found
    """
    if is_using_database():
        return _db_get_conversation(conversation_id)
    return _json_get_conversation(conversation_id)


def save_conversation(conversation: Dict[str, Any]):
    """
    Save a conversation to storage.

    Args:
        conversation: Conversation dict to save
    """
    if is_using_database():
        _db_save_conversation(conversation)
    else:
        _json_save_conversation(conversation)


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
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["messages"].append({
        "role": "user",
        "content": content
    })

    save_conversation(conversation)


def add_assistant_message(
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None
):
    """
    Add an assistant message with all 3 stages to a conversation.

    Args:
        conversation_id: Conversation identifier
        stage1: List of individual model responses
        stage2: List of model rankings
        stage3: Final synthesized response
        metadata: Optional metadata including label_to_model and aggregate_rankings
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    message = {
        "role": "assistant",
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3
    }

    if metadata:
        message["metadata"] = metadata

    conversation["messages"].append(message)

    save_conversation(conversation)


def update_conversation_title(conversation_id: str, title: str):
    """
    Update the title of a conversation.

    Args:
        conversation_id: Conversation identifier
        title: New title for the conversation
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["title"] = title
    save_conversation(conversation)


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
