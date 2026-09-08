"""Real subprocess crash tests for durable JSON storage."""
import json
import os
import subprocess
import sys

import pytest

from backend import storage

CID = '00000000-0000-0000-0000-000000009001'

@pytest.mark.parametrize('phase', ['before', 'after'])
def test_process_crash_keeps_complete_old_or_new_file(tmp_path, monkeypatch, phase):
    monkeypatch.setattr(storage.config, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(storage, 'is_using_database', lambda: False)
    storage.create_conversation(CID)
    storage.add_user_message(CID, 'old')
    code = '''
import os,sys,linecache
from backend import storage
storage.config.DATA_DIR=sys.argv[1]
real_replace=os.replace
def replace(src,dst):
 if str(dst).endswith('.json'):
  if sys.argv[3]=='after': real_replace(src,dst)
  os._exit(23)
 return real_replace(src,dst)
os.replace=replace
def trace(frame,event,arg):
 if event=='line' and frame.f_code.co_name=='_json_update_conversation' and 'f.write(payload)' in linecache.getline(frame.f_code.co_filename,frame.f_lineno):
  os._exit(23)
 return trace
sys.settrace(trace)
storage.add_user_message(sys.argv[2],'new')
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path), CID, phase], env={**os.environ, 'PYTHON_DOTENV_DISABLED':'1','AUTH_ENABLED':'false','DATABASE_TYPE':'json'}, timeout=15)
    assert result.returncode == 23
    saved = json.loads((tmp_path / f'{CID}.json').read_text())
    assert [m['content'] for m in saved['messages']] in [['old'], ['old', 'new']]


def test_corruption_recovers_backup_and_quarantines_original(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.config, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(storage, 'is_using_database', lambda: False)
    storage.create_conversation(CID)
    storage.add_user_message(CID, 'old')
    storage.add_user_message(CID, 'latest')
    (tmp_path / f'{CID}.json').write_text('broken')
    recovered = storage.get_conversation(CID)
    assert recovered is not None
    assert recovered['messages'][0]['content'] == 'old'
    assert list(tmp_path.glob(f'{CID}.json.corrupt-*'))
    assert storage.delete_conversation(CID)
    assert storage.get_conversation(CID) is None
    assert not (tmp_path / f'{CID}.json.bak').exists()


def test_missing_lookup_does_not_create_lock_files(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.config, 'DATA_DIR', str(tmp_path))
    assert storage._json_get_conversation(CID) is None
    assert not list(tmp_path.iterdir())


def test_delete_removes_interrupted_write_temporary_files(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.config, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(storage, 'is_using_database', lambda: False)
    storage.create_conversation(CID, username='alice')
    temporary = tmp_path / f'{CID}.json.bak.abandoned.tmp'
    temporary.write_text('private prompt')
    assert storage.delete_conversation(CID, username='alice')
    assert not temporary.exists()
