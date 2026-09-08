"""HTTP -> process crash -> restart -> HTTP durability contract."""
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

@pytest.mark.parametrize('phase', ['before', 'after'])
def test_http_title_survives_writer_crash_and_restart(tmp_path, phase):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'PYTHON_DOTENV_DISABLED':'1', 'AUTH_ENABLED':'false', 'AUTH_USERS':'{}',
           'DATABASE_TYPE':'json','DATA_DIR':str(tmp_path),'ENABLE_MEMORY':'false', 'ROUTER_TYPE':'ollama'}
    code = '''
import os,sys
from pathlib import Path as FilePath
import uvicorn
real_replace=os.replace
def replace(src,dst):
 if str(dst).endswith('.json') and 'CRASH_ME' in FilePath(src).read_text():
  if sys.argv[2]=='after': real_replace(src,dst)
  os._exit(23)
 return real_replace(src,dst)
if sys.argv[2]!='normal':os.replace=replace
uvicorn.run('backend.main:app',host='127.0.0.1',port=int(sys.argv[1]),log_level='error')
'''
    def start(mode):
        proc = subprocess.Popen([sys.executable,'-c',code,str(port),mode],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if httpx.get(f'http://127.0.0.1:{port}/',timeout=.2).status_code == 200:
                    return proc
            except httpx.HTTPError:
                pass
            if proc.poll() is not None:
                raise AssertionError(f'server exited {proc.returncode}')
            time.sleep(.05)
        proc.terminate()
        proc.wait(timeout=5)
        raise AssertionError('server startup timed out')
    proc = start(phase)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=5) as client:
            created = client.post('/api/conversations',json={})
            assert created.status_code == 200
            cid = created.json()['id']
            with pytest.raises(httpx.TransportError):
                client.patch(f'/api/conversations/{cid}/title',json={'title':'CRASH_ME'})
        assert proc.wait(timeout=5) == 23
        proc = start('normal')
        response = httpx.get(f'http://127.0.0.1:{port}/api/conversations/{cid}')
        assert response.status_code == 200
        assert response.json()['title'] in ['New Conversation','CRASH_ME']
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
