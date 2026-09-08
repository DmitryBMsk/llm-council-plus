"""Message attachment limits use raw bytes rather than base64 characters."""

import base64

import pytest
from pydantic import ValidationError

from backend.api.routes.conversations import FileAttachment, SendMessageRequest


MIB = 1024 * 1024


def image_data_uri(size: int) -> str:
    encoded = base64.b64encode(b"\0" * size).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def image_attachment(size: int, *, byte_size: int | None = None) -> dict:
    attachment = {
        "filename": "limit.png",
        "file_type": "image",
        "content": image_data_uri(size),
        "mime_type": "image/png",
    }
    if byte_size is not None:
        attachment["byte_size"] = byte_size
    return attachment


def test_image_above_old_five_mib_limit_is_accepted():
    attachment = FileAttachment.model_validate(image_attachment(6 * MIB))

    assert attachment.byte_size == 6 * MIB


def test_exact_twenty_mib_image_and_total_are_accepted():
    request = SendMessageRequest(
        content="Analyze this image",
        attachments=[image_attachment(20 * MIB, byte_size=20 * MIB)],
    )

    assert request.attachments[0].byte_size == 20 * MIB


def test_image_one_byte_over_twenty_mib_is_rejected_by_raw_size():
    with pytest.raises(ValidationError, match="20MB"):
        FileAttachment.model_validate(image_attachment(20 * MIB + 1))


def test_client_cannot_forge_image_byte_size():
    with pytest.raises(ValidationError, match="byte_size"):
        FileAttachment.model_validate(image_attachment(6 * MIB, byte_size=1))


def test_total_attachment_limit_uses_decoded_image_bytes():
    request = SendMessageRequest(
        content="Compare these images",
        attachments=[image_attachment(10 * MIB), image_attachment(10 * MIB)],
    )

    assert sum(attachment.byte_size for attachment in request.attachments) == 20 * MIB


def test_total_attachment_limit_rejects_one_raw_byte_over_twenty_mib():
    with pytest.raises(ValidationError, match="Total attachment size"):
        SendMessageRequest(
            content="Compare these images",
            attachments=[
                image_attachment(10 * MIB),
                image_attachment(10 * MIB + 1),
            ],
        )
