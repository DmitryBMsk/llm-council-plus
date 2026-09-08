"""Launch an isolated test service. Child environment excludes user secrets/.env."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
service = sys.argv[1]
provider_port = os.environ.get('E2E_PROVIDER_PORT', '18766')
backend_port = os.environ.get('E2E_BACKEND_PORT', '18765')
frontend_port = os.environ.get('E2E_FRONTEND_PORT', '5175')
preserved = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'SYSTEMROOT') if key in os.environ}
os.environ.clear()
os.environ.update(preserved)
os.environ.update(PYTHON_DOTENV_DISABLED='1', ROUTER_TYPE='ollama',
    OLLAMA_HOST=f'127.0.0.1:{provider_port}', AUTH_ENABLED='false',
    COUNCIL_MODELS='e2e-alpha:latest,e2e-beta:latest', CHAIRMAN_MODEL='e2e-chair:latest',
    ENABLE_MEMORY='false', ENABLE_TAVILY='false', ENABLE_EXA='false', ENABLE_BRAVE='false',
    DATABASE_TYPE='json', LOG_LEVEL='WARNING', RUN_RATE_REQUESTS='200', OPENROUTER_API_KEY='e2e-no-secret',
    OPENROUTER_API_URL=f'http://127.0.0.1:{provider_port}/v1/chat/completions')
sys.path.insert(0, str(ROOT))

if service == 'frontend':
    os.environ['VITE_API_BASE'] = f'http://localhost:{backend_port}'
    os.chdir(ROOT / 'frontend')
    # --mode e2e and empty temporary envDir prevent Vite loading user .env files.
    # Vite's --config supports generated config importing existing project config.
    with tempfile.TemporaryDirectory(prefix='council-e2e-vite-') as temp:
        config = Path(temp) / 'vite.config.mjs'
        config.write_text(f'import base from {str(ROOT / "frontend/vite.config.js")!r};\n'
                          f'export default {{...base, envDir: {temp!r}}};\n')
        import subprocess
        raise SystemExit(subprocess.call(['node', 'node_modules/vite/bin/vite.js', '--host', 'localhost',
            '--port', frontend_port, '--strictPort', '--mode', 'e2e', '--config', str(config)]))
else:
    import uvicorn
    with tempfile.TemporaryDirectory(prefix='council-e2e-data-') as temp:
        os.environ['DATA_DIR'] = str(Path(temp) / 'conversations')
        os.environ['RUNTIME_SETTINGS_FILE'] = str(Path(temp) / 'settings.json')
        os.chdir(temp)
        target = 'e2e.fixture_app:app' if service == 'provider' else 'e2e.fixture_app:backend_app'
        uvicorn.run(target, host='127.0.0.1', port=int(provider_port if service == 'provider' else backend_port),
                    log_level='warning', factory=service == 'backend')
