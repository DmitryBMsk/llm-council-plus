"""Follow-up context retains successful model answers in every council mode."""
import pytest
from backend import council


@pytest.mark.parametrize('mode', ['chat_only', 'chat_ranking', 'full'])
def test_followup_includes_previous_answer(mode):
    assistant = {'role': 'assistant', 'stage1': [
        {'model': 'model-a', 'response': 'CODE_42'},
        {'model': 'model-b', 'response': 'Other perspective'},
        {'model': 'broken', 'error': True, 'response': 'FAILURE_SECRET'},
    ], 'stage3': {'response': 'FINAL_42'} if mode == 'full' else None}
    prompt = council.build_context_prompt([
        {'role': 'user', 'content': 'Earlier question'}, assistant,
    ], 'Explain your answer')
    assert ('FINAL_42' if mode == 'full' else 'CODE_42') in prompt
    assert 'FAILURE_SECRET' not in prompt
    if mode != 'full':
        assert 'model-a' in prompt and 'Other perspective' in prompt
    else:
        assert 'Other perspective' not in prompt


def test_partial_answer_obeys_history_budget():
    prompt = council.build_context_prompt([{'role': 'assistant', 'stage1': [
        {'model': 'a', 'response': 'x' * 50_000},
    ]}], 'Continue')
    assert '[earlier context omitted]' in prompt
    assert len(prompt) < council.MAX_CONTEXT_CHARS + 1000


def test_failed_synthesis_uses_successful_individual_answers():
    prompt = council.build_context_prompt([{'role': 'assistant',
        'stage1': [{'model': 'a', 'response': 'usable'}],
        'stage3': {'error': True, 'response': 'failed'},
    }], 'Continue')
    assert 'usable' in prompt
    assert 'failed' not in prompt


def test_multilingual_history_respects_token_budget():
    from backend.toon_encoder import count_tokens
    prompt = council.build_context_prompt([{'role': 'assistant', 'stage1': [
        {'model': 'a', 'response': '漢字🚀 ' * 7000},
    ]}], 'Continue')
    history = prompt.split('Previous conversation:\n', 1)[1].split('\n\nCurrent follow-up', 1)[0]
    assert count_tokens(history) <= 6000
