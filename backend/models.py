"""SQLAlchemy models for PostgreSQL and MySQL."""

from sqlalchemy import Column, String, Text, DateTime, JSON, Index
from sqlalchemy.sql import func
from .database import Base


class Conversation(Base):
    """
    Conversation model - stores conversation metadata and messages.

    Compatible with both PostgreSQL and MySQL.
    """

    __tablename__ = "conversations"

    # Primary key
    id = Column(String(36), primary_key=True, index=True)  # UUID

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    title = Column(String(500), nullable=False, default="New Conversation")

    # Messages stored as JSON
    # PostgreSQL: Uses native JSONB (faster)
    # MySQL: Uses JSON type (MySQL 5.7.8+)
    messages = Column(JSON, nullable=False, default=list)

    # Custom fields for model selection
    models = Column(JSON, nullable=True)  # List of council model IDs
    chairman = Column(String(255), nullable=True)  # Chairman/judge model ID
    username = Column(String(255), nullable=True)  # User who created the conversation

    # Indexes for performance
    __table_args__ = (
        Index("idx_created_at", "created_at"),
        Index("idx_title", "title"),
        Index("idx_username", "username"),
    )

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "title": self.title,
            "messages": self.messages or [],
            "models": self.models,
            "chairman": self.chairman,
            "username": self.username,
        }

    def __repr__(self):
        return f"<Conversation(id={self.id}, title={self.title}, messages={len(self.messages or [])})>"
