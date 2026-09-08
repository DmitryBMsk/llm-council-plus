"""Concurrent mutation contract, also executable against real SQL servers."""

from concurrent.futures import ThreadPoolExecutor
import os
import threading
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import storage
from backend.database import Base


@pytest.mark.parametrize("kind", ["user", "assistant", "title"])
def test_concurrent_sql_updates_preserve_messages(tmp_path, monkeypatch, kind):
    url = os.getenv("SQL_TEST_URL", f"sqlite:///{tmp_path}/test.db")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(storage, "is_using_database", lambda: True)
    cid = str(uuid.uuid4())
    storage.create_conversation(cid, system_prompt="preserve me")
    original_get = storage.get_conversation
    barrier = threading.Barrier(2)

    def gated_get(*a, **kw):
        result = original_get(*a, **kw)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(storage, "get_conversation", gated_get)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(storage.add_user_message, cid, "A")
            if kind == "user":
                second = pool.submit(storage.add_user_message, cid, "B")
            elif kind == "assistant":
                second = pool.submit(storage.add_assistant_message, cid, [{"model": "m", "response": "B"}])
            else:
                second = pool.submit(storage.update_conversation_title, cid, "updated")
            first.result(timeout=10)
            second.result(timeout=10)
        loaded = original_get(cid)
        assert len(loaded["messages"]) == (1 if kind == "title" else 2)
        assert loaded["system_prompt"] == "preserve me"
        if kind == "title":
            assert loaded["title"] == "updated"
    finally:
        storage._db_delete_conversation(cid)
        engine.dispose()
