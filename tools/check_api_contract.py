"""Check reviewed OpenAPI schema drift without loading local credentials."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(PYTHON_DOTENV_DISABLED='1', AUTH_ENABLED='false', AUTH_USERS='{}', DATABASE_TYPE='json', ENABLE_MEMORY='false', ROUTER_TYPE='ollama')

from backend.main import app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true', help='Update after intentional API review')
    args = parser.parse_args()
    target = ROOT / 'docs/api/openapi.json'
    schema = json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + '\n'
    if args.write:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(schema)
        print('OpenAPI snapshot updated')
    elif not target.exists() or target.read_text() != schema:
        raise SystemExit('OpenAPI contract changed. Review it, then run tools/check_api_contract.py --write')
    else:
        print('OpenAPI contract matches')


if __name__ == '__main__':
    main()
