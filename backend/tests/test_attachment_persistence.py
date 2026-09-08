"""Real HTTP/storage contracts, with model generation replaced by a local stub."""
import base64
import hashlib
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import config, storage
from backend.api.deps import get_current_user
from backend.api.routes import conversations as routes
from backend.council import build_context_prompt


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(config, 'AUTH_ENABLED', True)
    monkeypatch.setattr(storage, 'is_using_database', lambda: False)
    monkeypatch.setattr(routes, 'generate_conversation_title', AsyncMock(return_value='Attachment test'))
    monkeypatch.setattr(routes, 'run_full_council', AsyncMock(return_value=([], [], None, {})))
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: 'alice'
    with TestClient(app) as client:
        yield app, client


def new_conversation(router_type='openrouter'):
    cid = str(uuid.uuid4())
    storage.create_conversation(cid, username='alice', router_type=router_type)
    return cid


def image_attachment():
    return dict(filename='image.png', file_type='image', content='data:image/png;base64,' + base64.b64encode(b'image bytes').decode())


def test_upload_send_reload_download_followup_text(app_client):
    app, client = app_client
    cid = new_conversation()
    attachment = client.post('/api/upload', files={'file': ('brief.txt', b'UNIQUE_DOCUMENT_FACT', 'text/plain')}).json()
    assert client.post(f'/api/conversations/{cid}/message', json={'content': 'Read this', 'attachments': [attachment]}).status_code == 200
    msg = client.get(f'/api/conversations/{cid}').json()['messages'][0]
    saved = msg['attachments'][0]
    assert saved['sha256'] == hashlib.sha256(b'UNIQUE_DOCUMENT_FACT').hexdigest()
    assert saved['content'] == 'UNIQUE_DOCUMENT_FACT'
    assert saved['hash_basis'] == 'stored_extracted_utf8'
    assert 'UNIQUE_DOCUMENT_FACT' in build_context_prompt([msg], 'What did the brief say?')
    response = client.get(f'/api/conversations/{cid}/attachments/{saved["id"]}')
    assert response.content == b'UNIQUE_DOCUMENT_FACT'
    app.dependency_overrides[get_current_user] = lambda: 'bob'
    assert client.get(f'/api/conversations/{cid}/attachments/{saved["id"]}').status_code == 404


def test_images_stored_as_bytes_reused_and_deleted(app_client):
    _, client = app_client
    cid = new_conversation()
    assert client.post(f'/api/conversations/{cid}/message', json={'content': 'Image?', 'attachments': [image_attachment()]}).status_code == 200
    saved = client.get(f'/api/conversations/{cid}').json()['messages'][0]['attachments'][0]
    assert 'content' not in saved
    assert saved['sha256'] == hashlib.sha256(b'image bytes').hexdigest()
    files = list(__import__('pathlib').Path(config.DATA_DIR).rglob(saved['id']))
    assert len(files) == 1 and files[0].read_bytes() == b'image bytes'
    assert client.get(f'/api/conversations/{cid}/attachments/{saved["id"]}').content == b'image bytes'
    assert client.post(f'/api/conversations/{cid}/message', json={'content': 'Describe it again'}).status_code == 200
    assert routes.run_full_council.call_args.kwargs['images'][0]['content'] == image_attachment()['content']
    assert client.delete(f'/api/conversations/{cid}').status_code == 200
    assert not files[0].exists()


@pytest.mark.parametrize('suffix', ['message', 'message/stream'])
def test_ollama_image_rejected_before_message_saved(app_client, suffix):
    _, client = app_client
    cid = new_conversation('ollama')
    response = client.post(f'/api/conversations/{cid}/{suffix}', json={'content': 'Image?', 'attachments': [image_attachment()]})
    assert response.status_code == 400
    assert 'Ollama' in response.json()['detail']
    assert storage.get_conversation(cid)['messages'] == []
    routes.run_full_council.assert_not_called()


def test_attachment_lookup_invalid_ids_and_unreferenced_files_are_not_downloadable(app_client):
    _, client = app_client
    cid = new_conversation()
    assert client.get(f'/api/conversations/{cid}/attachments/not-a-hash').status_code == 404
    assert client.get(f'/api/conversations/not-a-uuid/attachments/{"a" * 64}').status_code == 404
    assert client.get(f'/api/conversations/{cid}/attachments/{"a" * 64}').status_code == 404


def test_scoped_delete_all_removes_only_owned_image_files(app_client):
    _, client = app_client
    from pathlib import Path
    alice = new_conversation()
    bob = str(uuid.uuid4())
    storage.create_conversation(bob, username='bob')
    storage.add_user_message(alice, 'a', [image_attachment()])
    storage.add_user_message(bob, 'b', [image_attachment()])
    assert client.delete('/api/conversations').status_code == 200
    root = Path(config.DATA_DIR) / 'attachments'
    assert not (root / alice).exists()
    assert (root / bob).exists()
    assert storage.get_conversation(bob)


def test_attachment_path_rejects_traversal_and_symlinks(tmp_path, monkeypatch):
    from backend import attachments
    monkeypatch.setattr(config, 'DATA_DIR', str(tmp_path))
    with pytest.raises(ValueError):
        attachments.image_path('../escape', 'a' * 64)
    with pytest.raises(ValueError):
        attachments.image_path(str(uuid.uuid4()), '../escape')
    (tmp_path / 'attachments').symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(ValueError):
        attachments.image_path(str(uuid.uuid4()), 'a' * 64)
