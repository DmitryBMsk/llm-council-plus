"""Conversation memory with optional embeddings backend.

Memory feature requires optional dependencies (sentence-transformers, chromadb).
If not installed, memory is gracefully disabled.
"""

from __future__ import annotations

import os
from typing import Optional
from pathlib import Path

# Try to import heavy dependencies - they are optional
_MEMORY_AVAILABLE = False
try:
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_community.vectorstores import Chroma
    _MEMORY_AVAILABLE = True
except ImportError:
    HuggingFaceEmbeddings = None
    Chroma = None


def get_embeddings():
    """Return embeddings implementation based on env flags."""
    if not _MEMORY_AVAILABLE:
        return None

    if os.getenv("ENABLE_OPENAI_EMBEDDINGS", "false").lower() == "true":
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            try:
                from langchain_openai import OpenAIEmbeddings

                return OpenAIEmbeddings(api_key=api_key)
            except Exception:
                # Fall back to local embeddings on failure
                pass

    # Free local embeddings
    try:
        return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    except Exception:
        return None


class CouncilMemorySystem:
    """Lightweight per-conversation memory backed by Chroma."""

    def __init__(self, conversation_id: str):
        self.enabled = os.getenv("ENABLE_MEMORY", "true").lower() == "true"
        self.conversation_id = conversation_id
        self.retriever = None
        self.vectorstore = None

        # Disable if dependencies aren't available
        if not _MEMORY_AVAILABLE:
            self.enabled = False
            return

        if not self.enabled:
            return

        embeddings = get_embeddings()
        if embeddings is None:
            self.enabled = False
            return

        try:
            store_path = Path("./data/memory") / conversation_id
            store_path.mkdir(parents=True, exist_ok=True)

            self.vectorstore = Chroma(
                collection_name=f"conv_{conversation_id}",
                embedding_function=embeddings,
                persist_directory=str(store_path),
            )
            self.retriever = self.vectorstore.as_retriever(search_kwargs={"k": 3})
        except Exception:
            self.enabled = False
            self.vectorstore = None
            self.retriever = None

    def get_context(self, query: str) -> str:
        """Retrieve relevant context for a query."""
        if not self.enabled or self.retriever is None:
            return ""
        try:
            docs = self.retriever.get_relevant_documents(query)
            if not docs:
                return ""
            return "\n".join(doc.page_content for doc in docs if doc.page_content).strip()
        except Exception as e:
            # Consider logging the exception for debugging purposes, e.g.:
            # import logging
            # logging.error(f"Error retrieving memory context: {e}")
            return ""

    def save_exchange(self, user_msg: str, assistant_msg: str):
        """Persist a user/assistant exchange."""
        if not self.enabled or self.vectorstore is None:
            return
        try:
            content = f"User: {user_msg}\nAssistant: {assistant_msg}"
            self.vectorstore.add_texts([content])
        except Exception:
            return
