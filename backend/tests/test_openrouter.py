"""Tests for openrouter module - multimodal support."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import json


class TestMultimodalSupport:
    """Test multimodal message building and API calls."""

    def test_build_multimodal_message_text_only(self):
        """Test building a message with text only."""
        from ..openrouter import build_message_content

        content = build_message_content("Hello, world!")

        assert content == "Hello, world!"

    def test_build_multimodal_message_with_images(self):
        """Test building a message with text and images."""
        from ..openrouter import build_message_content

        images = [
            {"content": "data:image/jpeg;base64,abc123", "filename": "photo.jpg"}
        ]
        content = build_message_content("What is in this image?", images)

        assert isinstance(content, list)
        assert len(content) == 2

        # First should be text
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "What is in this image?"

        # Second should be image
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == "data:image/jpeg;base64,abc123"

    def test_build_multimodal_message_multiple_images(self):
        """Test building a message with multiple images."""
        from ..openrouter import build_message_content

        images = [
            {"content": "data:image/jpeg;base64,abc123", "filename": "photo1.jpg"},
            {"content": "data:image/png;base64,def456", "filename": "photo2.png"},
        ]
        content = build_message_content("Compare these images", images)

        assert isinstance(content, list)
        assert len(content) == 3  # 1 text + 2 images

        # First is text
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Compare these images"

        # Second and third are images
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == "data:image/jpeg;base64,abc123"
        assert content[2]["type"] == "image_url"
        assert content[2]["image_url"]["url"] == "data:image/png;base64,def456"

    def test_build_multimodal_message_empty_images(self):
        """Test building a message with empty images list."""
        from ..openrouter import build_message_content

        content = build_message_content("Hello", images=[])

        # Should return plain string when no images
        assert content == "Hello"

    @pytest.mark.asyncio
    async def test_query_model_multimodal_payload(self):
        """Test that query_model sends correct payload for multimodal."""
        from ..openrouter import query_model

        # Mock the httpx client
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "I see a cat in the image.",
                    "role": "assistant"
                }
            }]
        }
        mock_response.raise_for_status = MagicMock()

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            # Build multimodal message
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image?"},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc123"}}
                ]
            }]

            result = await query_model("openai/gpt-4o", messages)

            assert result is not None
            assert result["content"] == "I see a cat in the image."

            # Verify the payload structure
            call_args = mock_client.post.call_args
            payload = call_args.kwargs.get('json') or call_args[1].get('json')
            assert payload["messages"] == messages
