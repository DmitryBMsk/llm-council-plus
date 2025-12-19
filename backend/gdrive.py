"""Google Drive integration for uploading conversation exports."""

import os
import io
from typing import Optional, Dict, Any
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from .config import (
    GOOGLE_DRIVE_FOLDER_ID,
    GOOGLE_SERVICE_ACCOUNT_FILE,
    GOOGLE_DRIVE_ENABLED
)


# Scopes required for Google Drive file upload
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Cached service instance
_drive_service = None


def get_drive_service():
    """
    Get or create Google Drive service instance.
    Uses service account credentials.
    """
    global _drive_service

    if _drive_service is not None:
        return _drive_service

    if not GOOGLE_DRIVE_ENABLED:
        raise ValueError("Google Drive is not configured. Set GOOGLE_DRIVE_FOLDER_ID in .env")

    if not os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(
            f"Service account file not found: {GOOGLE_SERVICE_ACCOUNT_FILE}. "
            "Please download it from Google Cloud Console."
        )

    credentials = service_account.Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_FILE,
        scopes=SCOPES
    )

    _drive_service = build('drive', 'v3', credentials=credentials)
    return _drive_service


def upload_to_drive(
    filename: str,
    content: str,
    mime_type: str = 'text/markdown',
    folder_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Upload a file to Google Drive.

    Args:
        filename: Name of the file to create
        content: File content as string
        mime_type: MIME type of the file
        folder_id: Optional folder ID (defaults to GOOGLE_DRIVE_FOLDER_ID)

    Returns:
        Dict with file info including id, name, and webViewLink
    """
    if not GOOGLE_DRIVE_ENABLED:
        raise ValueError("Google Drive is not configured")

    service = get_drive_service()
    target_folder = folder_id or GOOGLE_DRIVE_FOLDER_ID

    # File metadata
    file_metadata = {
        'name': filename,
        'parents': [target_folder]
    }

    # Create media upload from string content
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode('utf-8')),
        mimetype=mime_type,
        resumable=True
    )

    # Upload file
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, name, webViewLink, webContentLink'
    ).execute()

    return {
        'id': file.get('id'),
        'name': file.get('name'),
        'webViewLink': file.get('webViewLink'),
        'webContentLink': file.get('webContentLink')
    }


def is_drive_configured() -> bool:
    """Check if Google Drive is properly configured."""
    if not GOOGLE_DRIVE_ENABLED:
        return False

    if not os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE):
        return False

    return True


def get_drive_status() -> Dict[str, Any]:
    """Get Google Drive configuration status."""
    return {
        'enabled': GOOGLE_DRIVE_ENABLED,
        'configured': is_drive_configured(),
        'folder_id': GOOGLE_DRIVE_FOLDER_ID if GOOGLE_DRIVE_ENABLED else None
    }
