"""Tests for file_parser module - image support."""

import pytest
import base64
from ..file_parser import (
    parse_file,
    parse_image,
    get_supported_extensions,
    is_image_file,
    get_image_mime_type,
    IMAGE_EXTENSIONS
)


class TestImageSupport:
    """Test image parsing functionality."""

    def test_image_extensions_defined(self):
        """Test that image extensions are defined."""
        assert '.jpg' in IMAGE_EXTENSIONS
        assert '.jpeg' in IMAGE_EXTENSIONS
        assert '.png' in IMAGE_EXTENSIONS
        assert '.gif' in IMAGE_EXTENSIONS
        assert '.webp' in IMAGE_EXTENSIONS

    def test_supported_extensions_include_images(self):
        """Test that supported extensions include image formats."""
        extensions = get_supported_extensions()
        assert '.jpg' in extensions
        assert '.jpeg' in extensions
        assert '.png' in extensions
        assert '.gif' in extensions
        assert '.webp' in extensions
        # Also still include text formats
        assert '.pdf' in extensions
        assert '.txt' in extensions
        assert '.md' in extensions

    def test_is_image_file(self):
        """Test image file detection."""
        assert is_image_file('photo.jpg') is True
        assert is_image_file('Photo.JPG') is True
        assert is_image_file('image.jpeg') is True
        assert is_image_file('screenshot.png') is True
        assert is_image_file('animation.gif') is True
        assert is_image_file('modern.webp') is True
        assert is_image_file('document.pdf') is False
        assert is_image_file('readme.txt') is False
        assert is_image_file('notes.md') is False

    def test_get_image_mime_type(self):
        """Test MIME type detection for images."""
        assert get_image_mime_type('image.jpg') == 'image/jpeg'
        assert get_image_mime_type('image.jpeg') == 'image/jpeg'
        assert get_image_mime_type('image.png') == 'image/png'
        assert get_image_mime_type('image.gif') == 'image/gif'
        assert get_image_mime_type('image.webp') == 'image/webp'
        assert get_image_mime_type('IMAGE.PNG') == 'image/png'

    def test_parse_image_returns_base64(self):
        """Test that parse_image returns base64 encoded data."""
        # Create a simple 1x1 pixel PNG (smallest valid PNG)
        # This is the actual binary data for a 1x1 red PNG
        png_data = bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,  # 1x1
            0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
            0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,  # IDAT chunk
            0x54, 0x08, 0xD7, 0x63, 0xF8, 0xFF, 0xFF, 0x3F,
            0x00, 0x05, 0xFE, 0x02, 0xFE, 0xDC, 0xCC, 0x59,
            0xE7, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E,  # IEND chunk
            0x44, 0xAE, 0x42, 0x60, 0x82
        ])

        result = parse_image(png_data, 'test.png')

        # Should return a data URI
        assert result.startswith('data:image/png;base64,')
        # Base64 part should be decodable
        base64_part = result.split(',')[1]
        decoded = base64.b64decode(base64_part)
        assert decoded == png_data

    def test_parse_image_jpeg(self):
        """Test JPEG image parsing."""
        # Minimal JPEG (not valid image but valid base64 encoding)
        jpeg_data = b'\xff\xd8\xff\xe0\x00\x10JFIF'

        result = parse_image(jpeg_data, 'photo.jpg')

        assert result.startswith('data:image/jpeg;base64,')

    def test_parse_file_detects_images(self):
        """Test that parse_file correctly handles image files."""
        png_data = bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
            0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,
            0x54, 0x08, 0xD7, 0x63, 0xF8, 0xFF, 0xFF, 0x3F,
            0x00, 0x05, 0xFE, 0x02, 0xFE, 0xDC, 0xCC, 0x59,
            0xE7, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E,
            0x44, 0xAE, 0x42, 0x60, 0x82
        ])

        content, file_type = parse_file('screenshot.png', png_data)

        assert file_type == 'image'
        assert content.startswith('data:image/png;base64,')

    def test_parse_file_still_handles_text(self):
        """Test that text files still work after adding image support."""
        txt_content = b'Hello, world!'

        content, file_type = parse_file('test.txt', txt_content)

        assert file_type == 'txt'
        assert content == 'Hello, world!'
