"""Google Drive endpoints — /api/drive/*."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from ...gdrive import upload_to_drive, get_drive_status, is_drive_configured
from ..deps import get_current_user

router = APIRouter(tags=["drive"])


class DriveUploadRequest(BaseModel):
    """Request to upload content to Google Drive."""
    filename: str = Field(max_length=255, pattern=r'^[^/\\<>:"|?*\x00-\x1f]+$')  # Safe filename
    content: str = Field(max_length=10_000_000)  # 10MB content limit


@router.get("/api/drive/status")
async def drive_status():
    """Get Google Drive configuration status."""
    return get_drive_status()


@router.post("/api/drive/upload")
async def drive_upload(
    request: DriveUploadRequest,
    current_user: str = Depends(get_current_user)
):
    """
    Upload markdown content to Google Drive. Requires authentication.
    Returns file info including view link.
    """
    if not is_drive_configured():
        raise HTTPException(
            status_code=503,
            detail="Google Drive is not configured. Set GOOGLE_DRIVE_FOLDER_ID and add service account credentials."
        )

    try:
        result = upload_to_drive(
            filename=request.filename,
            content=request.content,
            mime_type='text/markdown'
        )
        return {
            "success": True,
            "file": result
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload to Google Drive: {str(e)}"
        )
