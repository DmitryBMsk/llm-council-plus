"""Regression tests for conversation settings stored in the SQL models column."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import storage
from backend.database import Base
from backend.models import Conversation


def test_db_save_conversation_preserves_system_prompt(monkeypatch):
    """Saving an existing SQL conversation must not discard its system prompt."""
    engine = create_engine("sqlite:///:memory:")
    sql_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    try:
        with sql_session() as db:
            db.add(
                Conversation(
                    id="conversation-1",
                    title="Old title",
                    messages=[],
                    models=["model-a"],
                )
            )
            db.commit()

        monkeypatch.setattr(storage, "SessionLocal", sql_session)
        storage._db_save_conversation(
            {
                "id": "conversation-1",
                "title": "Updated title",
                "messages": [{"role": "user", "content": "Question"}],
                "models": ["model-a", "model-b"],
                "chairman": "model-a",
                "username": "alice",
                "execution_mode": "full",
                "router_type": "openrouter",
                "system_prompt": "Keep this instruction",
            }
        )

        with sql_session() as db:
            saved = db.get(Conversation, "conversation-1")
            assert saved is not None
            assert saved.models == {
                "models": ["model-a", "model-b"],
                "execution_mode": "full",
                "router_type": "openrouter",
                "system_prompt": "Keep this instruction",
            }
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
