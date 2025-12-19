"""Tests for council module - multimodal support."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestMultimodalCouncil:
    """Test council functions with image support."""

    def test_build_context_prompt_with_images(self):
        """Test that images are separated from text in context building."""
        from ..council import build_multimodal_messages

        text_query = "What is in this image?"
        images = [
            {"content": "data:image/jpeg;base64,abc123", "filename": "photo.jpg"}
        ]

        messages = build_multimodal_messages(text_query, images)

        assert len(messages) == 1
        assert messages[0]["role"] == "user"

        # Content should be a list (multimodal)
        content = messages[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"

    def test_build_context_prompt_without_images(self):
        """Test that text-only queries return simple messages."""
        from ..council import build_multimodal_messages

        text_query = "What is Python?"

        messages = build_multimodal_messages(text_query, images=None)

        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        # Content should be a string (text only)
        assert isinstance(messages[0]["content"], str)
        assert messages[0]["content"] == "What is Python?"

    def test_build_context_prompt_with_history(self):
        """Test multimodal messages with conversation history."""
        from ..council import build_multimodal_messages

        text_query = "Compare it to this new image"
        images = [
            {"content": "data:image/png;base64,xyz789", "filename": "new.png"}
        ]
        history = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "stage3": {"response": "Python is a programming language."}}
        ]

        messages = build_multimodal_messages(text_query, images, conversation_history=history)

        assert len(messages) == 1
        # The content should include context from history in the text part
        content = messages[0]["content"]
        assert isinstance(content, list)
        text_part = content[0]["text"]
        assert "Previous conversation" in text_part or "Python" in text_part

    def test_build_context_prompt_multiple_images(self):
        """Test building context with multiple images."""
        from ..council import build_multimodal_messages

        text_query = "Compare these images"
        images = [
            {"content": "data:image/jpeg;base64,img1", "filename": "first.jpg"},
            {"content": "data:image/jpeg;base64,img2", "filename": "second.jpg"},
        ]

        messages = build_multimodal_messages(text_query, images)

        content = messages[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 3  # 1 text + 2 images
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        assert content[2]["type"] == "image_url"
