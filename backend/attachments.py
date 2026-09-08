"""Conversation-owned attachments; image bytes never enter conversation JSON.

Text is the upload parser's extracted (possibly truncated) UTF-8 content. Its
hash identifies those stored bytes, not an unavailable original PDF/document.
"""
import base64
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from . import config

MAX_REUSED_IMAGES = 5
MAX_REUSED_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_MIME_TYPES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}


def conversation_directory(conversation_id):
    try:
        uuid.UUID(conversation_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('Invalid conversation ID') from exc
    root = Path(config.DATA_DIR).resolve() / 'attachments'
    directory = root / conversation_id
    if directory.resolve().parent != root.resolve() or directory.is_symlink() or root.is_symlink():
        raise ValueError('Invalid attachment directory')
    return directory


def image_path(conversation_id, attachment_id):
    if not re.fullmatch(r'[a-f0-9]{64}', attachment_id):
        raise ValueError('Invalid attachment ID')
    directory = conversation_directory(conversation_id)
    path = directory / attachment_id
    if path.is_symlink():
        raise ValueError('Invalid attachment file')
    return path


def persist_attachments(conversation_id, attachments):
    records = []
    for attachment in attachments or []:
        item = dict(attachment)
        image = item['file_type'] == 'image'
        if image:
            header, encoded = item['content'].split(',', 1)
            mime_type = header[5:].split(';')[0]
            if mime_type not in IMAGE_MIME_TYPES:
                raise ValueError('Unsupported image MIME type')
            data = base64.b64decode(encoded, validate=True)
        else:
            data = item['content'].encode('utf-8')
            mime_type = 'text/plain; charset=utf-8'
        digest = hashlib.sha256(data).hexdigest()
        record = dict(id=digest, sha256=digest, filename=item['filename'],
                      file_type=item['file_type'], mime_type=mime_type,
                      byte_size=len(data), hash_basis='image_bytes' if image else 'stored_extracted_utf8')
        if image:
            path = image_path(conversation_id, digest)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.upload-')
                try:
                    with os.fdopen(fd, 'wb') as output:
                        output.write(data)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, path)
                    if os.name != 'nt':
                        # Persist both the file entry and newly created parent directories.
                        for directory in (path.parent, path.parent.parent, path.parent.parent.parent):
                            directory_fd = os.open(directory, os.O_RDONLY)
                            try:
                                os.fsync(directory_fd)
                            finally:
                                os.close(directory_fd)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
        else:
            record['content'] = item['content']
            record['char_count'] = len(item['content'])
        records.append(record)
    return records


def latest_images(conversation):
    """Reuse only the most recent image batch, bounded by send-request limits."""
    for message in reversed(conversation.get('messages', [])):
        images = [a for a in message.get('attachments', []) if a.get('file_type') == 'image']
        if not images:
            continue
        result = []
        total = 0
        for attachment in images[:MAX_REUSED_IMAGES]:
            path = image_path(conversation['id'], attachment['id'])
            size = path.stat().st_size
            total += size
            if total > MAX_REUSED_IMAGE_BYTES:
                raise ValueError('Saved images exceed follow-up limit; attach a smaller image batch')
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != attachment['id']:
                raise ValueError('Saved image is damaged; reattach it')
            result.append({'filename': attachment['filename'], 'content':
                           f"data:{attachment['mime_type']};base64,{base64.b64encode(data).decode('ascii')}"})
        return result
    return []


def find_attachment(conversation, attachment_id):
    if not re.fullmatch(r'[a-f0-9]{64}', attachment_id):
        return None
    for message in conversation.get('messages', []):
        for attachment in message.get('attachments', []):
            if attachment.get('id') == attachment_id:
                return attachment
    return None


def delete_attachments(conversation_id):
    directory = conversation_directory(conversation_id)
    if directory.exists():
        shutil.rmtree(directory)
