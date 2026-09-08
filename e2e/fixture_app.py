"""Local Ollama-compatible HTTP provider for browser E2E; never calls a real model."""
import asyncio
import time
from fastapi import FastAPI, Request

app = FastAPI()
calls = []
MODELS = ['e2e-alpha:latest', 'e2e-beta:latest', 'e2e-chair:latest']


@app.get('/api/tags')
def tags():
    return {'models': [{'name': name, 'details': {'family': 'e2e'}} for name in MODELS]}


@app.get('/__calls')
def recorded_calls():
    return calls


@app.post('/v1/chat/completions')
@app.post('/api/chat')
async def chat(request: Request):
    payload = await request.json()
    calls.append(payload)
    text = '\n'.join(str(m.get('content', '')) for m in payload['messages'])
    if "__SLOW_RUN__" in text:
        await asyncio.sleep(1)
    # Let the browser exercise intermediate streaming state without arbitrary
    # waits in tests. Capture the full model request for follow-up assertions.
    await asyncio.sleep(0.05)
    if 'Generate a very short title' in text:
        answer = 'Local council result'
    elif text.startswith('You are evaluating different responses'):
        answer = 'The responses agree.\n\nFINAL RANKING:\n1. Response A\n2. Response B\n3. Response C'
    else:
        answer = 'E2E_ANSWER_42: deterministic council response.'
    if request.url.path == '/v1/chat/completions':
        return {'model': payload['model'], 'choices': [{'message': {'role': 'assistant', 'content': answer}}],
                'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30, 'cost': 0.0}}
    return {'model': payload['model'], 'message': {'role': 'assistant', 'content': answer},
            'done': True, 'prompt_eval_count': 20, 'eval_count': 10}


def backend_app():
    """Real application; only the external model catalog is seeded locally."""
    from backend.main import app as application
    from backend.api.routes import models
    models._models_cache['openrouter'] = {
        'timestamp': time.time(),
        'data': {'router_type': 'openrouter', 'max_models': 5, 'models': [
            {'id': name, 'name': name, 'provider': 'E2E', 'context': '128K',
             'contextLength': 128000, 'inputPrice': 'FREE', 'outputPrice': 'FREE',
             'tier': 'free', 'isFree': True, 'modality': 'text+image->text',
             'description': 'Local E2E fixture with image input'} for name in MODELS
        ]},
    }
    models._free_preset_cache.update(timestamp=time.time(), data={"models": MODELS, "chairman": MODELS[0], "source": "local-fixture", "updated_at": "2026-09-08"})
    return application
