"""Google Drive integration for uploading conversation exports.

This feature is optional. The backend must be able to start even when the
Google API dependencies are not installed.
"""

import os
import io
from typing import Optional, Dict, Any

try:  # pragma: no cover
    from google.oauth2 import service_account  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.http import MediaIoBaseUpload  # type: ignore
except ImportError:  # pragma: no cover
    service_account = None
    build = None
    MediaIoBaseUpload = None

from . import config


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

    if not config.GOOGLE_DRIVE_ENABLED:
        raise ValueError("Google Drive is not configured. Set GOOGLE_DRIVE_FOLDER_ID in .env")

    if service_account is None or build is None or MediaIoBaseUpload is None:
        raise ImportError(
            "Google Drive dependencies are not installed. "
            "Install 'google-api-python-client' and 'google-auth' to enable Drive uploads."
        )

    if not os.path.exists(config.GOOGLE_SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(
            f"Service account file not found: {config.GOOGLE_SERVICE_ACCOUNT_FILE}. "
            "Please download it from Google Cloud Console."
        )

    credentials = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_FILE,
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
    if not config.GOOGLE_DRIVE_ENABLED:
        raise ValueError("Google Drive is not configured")

    service = get_drive_service()
    target_folder = folder_id or config.GOOGLE_DRIVE_FOLDER_ID

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
    if not config.GOOGLE_DRIVE_ENABLED:
        return False

    if service_account is None or build is None or MediaIoBaseUpload is None:
        return False

    if not os.path.exists(config.GOOGLE_SERVICE_ACCOUNT_FILE):
        return False

    return True


def get_drive_status() -> Dict[str, Any]:
    """Get Google Drive configuration status."""
    return {
        'enabled': config.GOOGLE_DRIVE_ENABLED,
        'configured': is_drive_configured(),
        'folder_id': config.GOOGLE_DRIVE_FOLDER_ID if config.GOOGLE_DRIVE_ENABLED else None
    }
