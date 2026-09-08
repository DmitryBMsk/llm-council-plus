"""File parsing utilities for PDF, TXT, MD, and image files."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Tuple

# Supported image extensions
IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp']

# MIME types for images
IMAGE_MIME_TYPES = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp'
}


class PdfParseLimit(ValueError):
    """Invalid PDF or a resource limit exceeded; API should respond 400."""


class PdfParseBusy(PdfParseLimit):
    """All local PDF slots occupied; API should respond 429 (catch first)."""


_PDF_PARSE_SLOTS = threading.BoundedSemaphore(2)


def parse_pdf(file_content: bytes) -> str:
    """Parse in a disposable process, with finite time, pages and output."""
    if len(file_content) > 10 * 1024 * 1024:
        raise PdfParseLimit('PDF exceeds input limit (10 MiB)')
    if not _PDF_PARSE_SLOTS.acquire(blocking=False):
        raise PdfParseBusy('PDF parser busy; retry shortly')
    process = None
    try:
        try:
            timeout = float(os.environ.get('PDF_PARSE_TIMEOUT_SECONDS', '20'))
        except ValueError as error:
            raise PdfParseLimit('Invalid PDF timeout configuration') from error
        if not 0 < timeout <= 300:
            raise PdfParseLimit('Invalid PDF timeout configuration')
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name('pdf_worker.py').resolve())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        try:
            output, _ = process.communicate(file_content, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.communicate()
            raise PdfParseLimit('PDF parsing exceeded time limit') from error
        if process.returncode or len(output) > 310_000:
            raise PdfParseLimit('PDF parsing exceeded resource limits')
        try:
            result = json.loads(output)
        except (ValueError, UnicodeDecodeError) as error:
            raise PdfParseLimit('PDF parser returned invalid output') from error
        if result.get('error'):
            raise PdfParseLimit(result['error'])
        return result['text'][:50_000]
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.communicate()
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except BrokenPipeError:
                        pass
        _PDF_PARSE_SLOTS.release()


def parse_txt(file_content: bytes) -> str:
    """
    Parse TXT file content.

    Args:
        file_content: Raw bytes of the TXT file

    Returns:
        Decoded text content
    """
    # Try UTF-8 first, then fallback to latin-1
    try:
        return file_content.decode('utf-8')
    except UnicodeDecodeError:
        return file_content.decode('latin-1')


def parse_md(file_content: bytes) -> str:
    """
    Parse MD (markdown) file content.

    Args:
        file_content: Raw bytes of the MD file

    Returns:
        Decoded markdown content
    """
    # MD files are just text, same as TXT
    return parse_txt(file_content)


def is_image_file(filename: str) -> bool:
    """
    Check if a file is an image based on its extension.

    Args:
        filename: Name of the file

    Returns:
        True if the file is an image, False otherwise
    """
    ext = '.' + filename.lower().split('.')[-1] if '.' in filename else ''
    return ext in IMAGE_EXTENSIONS


def get_image_mime_type(filename: str) -> str:
    """
    Get the MIME type for an image file.

    Args:
        filename: Name of the image file

    Returns:
        MIME type string (e.g., 'image/jpeg')
    """
    ext = '.' + filename.lower().split('.')[-1] if '.' in filename else ''
    return IMAGE_MIME_TYPES.get(ext, 'image/jpeg')


def parse_image(file_content: bytes, filename: str) -> str:
    """
    Parse an image file to a base64 data URI.

    Args:
        file_content: Raw bytes of the image file
        filename: Name of the file (to determine MIME type)

    Returns:
        Base64 data URI string (e.g., 'data:image/jpeg;base64,...')
    """
    mime_type = get_image_mime_type(filename)
    base64_data = base64.b64encode(file_content).decode('utf-8')
    return f"data:{mime_type};base64,{base64_data}"


def parse_file(filename: str, file_content: bytes) -> Tuple[str, str]:
    """
    Parse a file based on its extension.

    Args:
        filename: Name of the file (to determine extension)
        file_content: Raw bytes of the file

    Returns:
        Tuple of (parsed_content, file_type)
        For images: content is base64 data URI, file_type is 'image'

    Raises:
        ValueError: If file type is not supported
    """
    filename_lower = filename.lower()

    # Check for image files first
    if is_image_file(filename):
        return parse_image(file_content, filename), 'image'
    elif filename_lower.endswith('.pdf'):
        return parse_pdf(file_content), 'pdf'
    elif filename_lower.endswith('.txt'):
        return parse_txt(file_content), 'txt'
    elif filename_lower.endswith('.md') or filename_lower.endswith('.mdx'):
        return parse_md(file_content), 'md'
    else:
        raise ValueError(f"Unsupported file type: {filename}")


def get_supported_extensions() -> list:
    """Return list of supported file extensions."""
    return ['.pdf', '.txt', '.md', '.mdx'] + IMAGE_EXTENSIONS
